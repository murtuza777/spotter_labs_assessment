"""Interfaces and DTOs for third-party providers, so services never see vendor JSON."""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from planner.domain.models import LatLon, WeatherSample


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


@dataclass(slots=True)
class HourlySeries:
    """Hourly weather for one location. Index i is the hour `start + i` (UTC)."""

    start: datetime
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in_hr: list[float | None]
    snow_in_hr: list[float | None]

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=len(self.gust_mph) - 1)

    def covers(self, start: datetime, end: datetime) -> bool:
        return self.start <= start and end <= self.end

    def at(self, hour: datetime) -> WeatherSample | None:
        """The reading for `hour`, or None if any value is missing or not a valid reading.

        None means "unknown" and is never scored. Out-of-range hours (outside the forecast
        coverage that was fetched) are unknown too, never extrapolated.
        """
        i = int((hour - self.start).total_seconds() // 3600)
        series = (self.wind_mph, self.gust_mph, self.rain_in_hr, self.snow_in_hr)
        if i < 0 or any(i >= len(s) for s in series):
            return None
        values = tuple(s[i] for s in series)
        if not all(_is_reading(v) for v in values):
            return None
        wind, gust, rain, snow = values
        return WeatherSample(wind_mph=wind, gust_mph=gust, rain_in_hr=rain, snow_in_hr=snow)


def _is_reading(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


class WeatherProvider(Protocol):
    def hourly(
        self, cells: list[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlySeries]:
        """Series for as many cells as could be fetched; missing cells are left out."""
        ...


class Geocoder(Protocol):
    def search(self, query: str, limit: int = 6) -> list[Place]: ...
