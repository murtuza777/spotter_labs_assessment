"""Interfaces and DTOs for third-party providers, so services never see vendor JSON."""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from planner.domain.models import LatLon, WeatherSample
from planner.domain.timebucket import forecast_hour_for


class ProviderError(Exception):
    """A provider failed in a way the API should report (e.g. 502/503)."""

    def __init__(self, code: str, message: str, *, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True, slots=True)
class Place:
    label: str
    lat: float
    lon: float

    @property
    def point(self) -> LatLon:
        return LatLon(self.lat, self.lon)


@dataclass(frozen=True, slots=True)
class ProgressPoint:
    point_index: int
    distance_m: float
    travel_time_s: float


@dataclass(frozen=True, slots=True)
class RouteOption:
    points: list[LatLon]
    length_m: float
    duration_s: float
    progress: list[ProgressPoint] = field(default_factory=list)


class RoutingProvider(Protocol):
    def routes(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        depart_at: datetime,
        vehicle_weight_kg: int,
        max_alternatives: int = 0,
        via: LatLon | None = None,
    ) -> list[RouteOption]: ...


# The four readings every provider must supply, in HourlySeries / WeatherSample order.
FIELDS = ("wind_mph", "gust_mph", "rain_in_hr", "snow_in_hr")


@dataclass(slots=True)
class HourlySeries:
    """Normalized hourly weather for one location, the schema every provider maps into.

    Index i covers the hour that *ends* at `start + i` (UTC): gusts are that hour's maximum,
    rain and snow are that hour's amounts, in mph and in/hr. That is Open-Meteo's native
    convention and what `domain.timebucket.forecast_hour_for` assumes. Providers with a
    different convention convert before building a series. None means "unknown", never zero.
    """

    start: datetime
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in_hr: list[float | None]
    snow_in_hr: list[float | None]
    source: str = ""  # provider name, e.g. "weatherapi"
    fetched_at: datetime | None = None
    # The last hour that was asked for. A provider with a shorter horizon may return less;
    # hours past `end` but before this are known-unavailable, so the cache need not refetch.
    requested_end: datetime | None = None
    # Per field, per hour: the provider that supplied the value, where it isn't `source`
    # (set when a fallback provider filled gaps). None means every value is from `source`.
    field_sources: dict[str, list[str | None]] | None = None
    # The window the whole provider chain was consulted for (set by WeatherService), so a
    # cached series with known gaps in that window isn't refetched on every request.
    checked: tuple[datetime, datetime] | None = None

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=len(self.gust_mph) - 1)

    def covers(self, start: datetime, end: datetime) -> bool:
        last = max(self.end, self.requested_end) if self.requested_end else self.end
        return self.start <= start and end <= last

    def at(self, hour: datetime) -> WeatherSample | None:
        """The reading for `hour`, or None if any value is missing or not a valid reading.

        None means "unknown" and is never scored. Out-of-range hours (outside the forecast
        coverage that was fetched) are unknown too, never extrapolated.
        """
        values = self.values_at(hour)
        if values is None or not all(_is_reading(v) for v in values):
            return None
        wind, gust, rain, snow = values
        return WeatherSample(wind_mph=wind, gust_mph=gust, rain_in_hr=rain, snow_in_hr=snow)

    def values_at(self, hour: datetime) -> tuple[float | None, ...] | None:
        """The raw four values for `hour` (any may be None), or None outside the series."""
        i = self._index(hour)
        if i is None:
            return None
        return tuple(getattr(self, f)[i] for f in FIELDS)

    def sources_at(self, hour: datetime) -> dict[str, str] | None:
        """Which provider supplied each value at `hour`, or None if nothing is known."""
        i = self._index(hour)
        if i is None or not self.source:
            return None
        out = {}
        for f in FIELDS:
            filled = self.field_sources.get(f) if self.field_sources else None
            out[f] = (filled[i] if filled and i < len(filled) else None) or self.source
        return out

    @property
    def providers(self) -> list[str]:
        """Every provider that supplied at least one value, primary first."""
        names = [self.source] if self.source else []
        for per_hour in (self.field_sources or {}).values():
            names.extend(n for n in per_hour if n)
        return list(dict.fromkeys(names))

    def missing_hours(self, start: datetime, end: datetime) -> list[datetime]:
        """Forecast hours in [start, end] without a complete, valid reading. Like ETAs, a
        start between hour stamps rounds up to the next one."""
        hours, h = [], forecast_hour_for(start)
        while h <= end:
            if self.at(h) is None:
                hours.append(h)
            h += timedelta(hours=1)
        return hours

    def _index(self, hour: datetime) -> int | None:
        offset = hour - self.start
        if offset % timedelta(hours=1):
            return None  # not on an hour boundary of this series: never guess an alignment
        i = int(offset.total_seconds() // 3600)
        if i < 0 or any(i >= len(getattr(self, f)) for f in FIELDS):
            return None
        return i


def merge_series(base: HourlySeries, extra: HourlySeries) -> tuple[HourlySeries, int]:
    """`base` with its gaps filled from `extra`, and how many values were filled.

    A value is filled only from the *same* hour of `extra` (both are normalized to the hour
    ending at each UTC stamp), only where `base` has none, and only with a valid reading.
    Values `base` has are never replaced. The result spans both series' hours.
    """
    start = min(base.start, extra.start)
    end = max(base.end, extra.end)
    n = int((end - start).total_seconds() // 3600) + 1
    columns: dict[str, list[float | None]] = {f: [None] * n for f in FIELDS}
    sources: dict[str, list[str | None]] = {f: [None] * n for f in FIELDS}
    filled = 0
    for i in range(n):
        hour = start + timedelta(hours=i)
        own = base.values_at(hour)
        own_sources = base.sources_at(hour)
        other = extra.values_at(hour)
        for k, f in enumerate(FIELDS):
            if own is not None and _is_reading(own[k]):
                columns[f][i] = own[k]
                sources[f][i] = own_sources[f] if own_sources else base.source
            elif other is not None and _is_reading(other[k]):
                columns[f][i] = other[k]
                sources[f][i] = extra.source
                filled += 1
    merged = HourlySeries(
        start=start,
        **columns,
        source=base.source,
        fetched_at=_earliest(base.fetched_at, extra.fetched_at),
        requested_end=base.requested_end,
        field_sources={
            f: [None if src == base.source else src for src in sources[f]] for f in FIELDS
        },
    )
    return merged, filled


def _earliest(a: datetime | None, b: datetime | None) -> datetime | None:
    return min(a, b) if a and b else a or b


def _is_reading(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


@dataclass(slots=True)
class CallLog:
    """What one provider fetch did, for logs and the API's `meta.weather`."""

    requests: int = 0
    statuses: dict[str, int] = field(default_factory=dict)  # "200" / "429" / "timeout" -> count
    ms: int = 0

    def record(self, status: str) -> None:
        self.requests += 1
        self.statuses[status] = self.statuses.get(status, 0) + 1


class WeatherFetch(dict):
    """A provider's answer: {cell: HourlySeries} (a plain dict to callers), plus the reasons
    any requests failed and, if the provider said its quota is spent, until when."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []
        self.calls = CallLog()
        self.quota_exhausted_until: datetime | None = None


class WeatherProvider(Protocol):
    name: str

    def hourly(self, cells: list[LatLon], start: datetime, end: datetime) -> WeatherFetch:
        """Series for as many cells as could be fetched; missing cells are left out."""
        ...


class Geocoder(Protocol):
    def search(self, query: str, limit: int = 6) -> list[Place]: ...
