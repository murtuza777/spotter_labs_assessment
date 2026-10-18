"""Weather lookups on the model grid: cached per cell, fetched through a provider chain.

Flow for a set of grid cells and a time window [start, end]:
  1. Cache: each cell's normalized HourlySeries is cached for `ttl_s` (forecasts update about
     hourly). Entries older than the TTL are treated as missing even if the cache backend
     still returns them, so a stale forecast is never scored.
  2. Providers, in order. The first gets every cell that isn't cached. Each later provider
     gets only the cells still missing, or still missing a value (wind, gust, rain or snow)
     for some hour of the window, and fills just those gaps: same cell, same UTC hour, never
     replacing a value an earlier provider supplied. Every value records which provider
     supplied it. All providers return the same normalized schema (providers/base.py), so
     units never mix.
  3. Breaker: when a provider says its quota is spent, it is rate-limiting, or it rejects the
     key, it is skipped until the stated time (shared across workers via the cache) instead
     of being hammered with retries.
Values nobody could provide stay missing; downstream they are "unknown", never zero.
"""

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta

from django.core.cache import BaseCache

from planner.domain.geo import snap
from planner.domain.models import LatLon, WeatherSample
from planner.providers.base import HourlySeries, WeatherProvider, merge_series

log = logging.getLogger(__name__)

# Fetch at least this far ahead so one cached series serves the plan and the 48 h heatmap.
MIN_FETCH_HOURS = 72
MAX_FORECAST_HOURS = 16 * 24
CACHE_VERSION = 3  # bump when the normalized schema changes


@dataclass(frozen=True, slots=True)
class ProviderStats:
    name: str
    requests: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    cells_ok: int = 0  # cells this provider returned a forecast for
    cells_failed: int = 0  # cells it was asked for and returned nothing
    cells_used: int = 0  # cells where at least one stored value came from it
    ms: int = 0
    skipped: str | None = None  # why the provider wasn't called (its breaker is open)


@dataclass(frozen=True, slots=True)
class WeatherStats:
    cells: int
    cached: int
    fetched: int
    failed: int  # cells no provider returned anything for
    ms: int
    # Distinct provider failure reasons, prefixed with the provider name.
    errors: tuple[str, ...] = ()
    providers: tuple[ProviderStats, ...] = ()
    incomplete: int = 0  # cells with a forecast that still has gaps inside the window

    def as_dict(self) -> dict:
        d = asdict(self)
        d["errors"] = list(self.errors)
        d["providers"] = [asdict(p) for p in self.providers]
        return d

    @property
    def sources(self) -> dict[str, int]:
        """Cells fetched now that use each provider's values (cached cells are not counted)."""
        return {p.name: p.cells_used for p in self.providers if p.cells_used}


def provider_name(provider: object) -> str:
    return getattr(provider, "name", type(provider).__name__)


class WeatherService:
    def __init__(
        self,
        providers: WeatherProvider | Sequence[WeatherProvider],
        cache: BaseCache,
        *,
        grid_deg: float,
        ttl_s: int,
        model: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._providers = list(providers) if isinstance(providers, list | tuple) else [providers]
        if not self._providers:
            raise ValueError("at least one weather provider is required")
        self._cache = cache
        self._grid = grid_deg
        self._ttl = ttl_s
        # Cached series depend on which providers built them, so the chain is in the key.
        self._namespace = f"{'+'.join(self.provider_names)}:{model}"
        self._now = now

    @property
    def grid_deg(self) -> float:
        return self._grid

    @property
    def provider_names(self) -> list[str]:
        return [provider_name(p) for p in self._providers]

    def cell_for(self, point: LatLon) -> LatLon:
        return LatLon(snap(point.lat, self._grid), snap(point.lon, self._grid))

    def series_for(
        self, cells: Iterable[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlySeries]:
        """Hourly series covering [start, end] for each cell that could be fetched."""
        return self.series_with_stats(cells, start, end)[0]

    def series_with_stats(
        self, cells: Iterable[LatLon], start: datetime, end: datetime
    ) -> tuple[dict[LatLon, HourlySeries], WeatherStats]:
        t0 = time.perf_counter()
        wanted = list(dict.fromkeys(cells))
        keys = {cell: self._key(cell) for cell in wanted}
        cached = self._cache.get_many(list(keys.values()))
        found: dict[LatLon, HourlySeries] = {}
        missing: list[LatLon] = []
        for cell in wanted:
            series = cached.get(keys[cell])
            if series is not None and self._usable(series, start, end):
                found[cell] = series
            else:
                missing.append(cell)
        cached_count = len(wanted) - len(missing)

        assembled: dict[LatLon, HourlySeries] = {}
        provider_stats: list[ProviderStats] = []
        errors: list[str] = []
        if missing:
            fetch_start, fetch_end = self._fetch_window(start, end)
            for provider in self._providers:
                targets = [
                    c
                    for c in missing
                    if c not in assembled or assembled[c].missing_hours(start, end)
                ]
                if not targets:
                    break
                name = provider_name(provider)
                paused = self._cache.get(self._breaker_key(name))
                if paused:
                    provider_stats.append(ProviderStats(name, skipped=f"paused until {paused}"))
                    errors.append(f"{name}: skipped, paused until {paused}")
                    continue
                fetched = provider.hourly(targets, fetch_start, fetch_end)
                for cell, series in fetched.items():
                    if cell in assembled:
                        assembled[cell], _ = merge_series(assembled[cell], series)
                    else:
                        assembled[cell] = series
                calls = getattr(fetched, "calls", None)
                provider_stats.append(
                    ProviderStats(
                        name,
                        requests=calls.requests if calls else 0,
                        statuses=dict(calls.statuses) if calls else {},
                        cells_ok=len(fetched),
                        cells_failed=len(targets) - len(fetched),
                        ms=calls.ms if calls else 0,
                    )
                )
                provider_errors = list(getattr(fetched, "errors", []))
                errors.extend(f"{name}: {e}" for e in provider_errors)
                self._open_breaker(
                    name,
                    getattr(fetched, "quota_exhausted_until", None),
                    provider_errors[0] if provider_errors else "quota spent",
                )

            for series in assembled.values():
                series.checked = (start, end)
            if assembled:
                self._cache.set_many({keys[c]: s for c, s in assembled.items()}, timeout=self._ttl)
            found.update(assembled)
            provider_stats = [
                replace(p, cells_used=sum(p.name in s.providers for s in assembled.values()))
                for p in provider_stats
            ]

        stats = WeatherStats(
            cells=len(wanted),
            cached=cached_count,
            fetched=len(assembled),
            failed=len(missing) - len(assembled),
            ms=round((time.perf_counter() - t0) * 1000),
            errors=tuple(dict.fromkeys(errors)),
            providers=tuple(provider_stats),
            incomplete=sum(1 for s in found.values() if s.missing_hours(start, end)),
        )
        log.info(
            "weather cells=%d cached=%d fetched=%d failed=%d incomplete=%d ms=%d providers=%s",
            stats.cells,
            stats.cached,
            stats.fetched,
            stats.failed,
            stats.incomplete,
            stats.ms,
            [
                (p.name, p.requests, p.statuses, p.cells_ok, p.cells_used, p.skipped)
                for p in provider_stats
            ],
        )
        return found, stats

    def _usable(self, series: HourlySeries, start: datetime, end: datetime) -> bool:
        """A cached series serves this window if it is fresh, spans it, and either has no gaps
        in it or the whole chain was already asked about those gaps (until the TTL runs out)."""
        if not series.covers(start, end) or not self._fresh(series):
            return False
        checked = series.checked
        if checked and checked[0] <= start and end <= checked[1]:
            return True
        return not series.missing_hours(start, end)

    def _fresh(self, series: HourlySeries) -> bool:
        if series.fetched_at is None:
            return True  # no timestamp (tests/fakes); the cache TTL still applies
        return self._now() - series.fetched_at <= timedelta(seconds=self._ttl)

    def _open_breaker(self, name: str, until: datetime | None, reason: str) -> None:
        """Skip `name` until `until` (quota spent, rate-limited or key rejected)."""
        if not until:
            return
        seconds = int((until - self._now()).total_seconds())
        if seconds > 0:
            note = f"{until.isoformat(timespec='minutes')} ({reason[:120]})"
            self._cache.set(self._breaker_key(name), note, seconds)
            log.warning("weather provider=%s breaker open until %s", name, note)

    def _fetch_window(self, start: datetime, end: datetime) -> tuple[datetime, datetime]:
        now_hour = self._now().astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        fetch_start = min(start, now_hour)
        fetch_end = max(end, now_hour + timedelta(hours=MIN_FETCH_HOURS))
        return fetch_start, min(fetch_end, now_hour + timedelta(hours=MAX_FORECAST_HOURS))

    def _key(self, cell: LatLon) -> str:
        return f"wx:v{CACHE_VERSION}:{self._namespace}:{cell.lat:.3f}:{cell.lon:.3f}"

    @staticmethod
    def _breaker_key(name: str) -> str:
        return f"wx:breaker:{name}"


def sample(
    series: dict[LatLon, HourlySeries], cell: LatLon, hour: datetime
) -> WeatherSample | None:
    s = series.get(cell)
    return s.at(hour) if s else None


def sample_sources(
    series: dict[LatLon, HourlySeries], cell: LatLon, hour: datetime
) -> dict[str, str] | None:
    """Which provider supplied each value of `sample(series, cell, hour)`."""
    s = series.get(cell)
    return s.sources_at(hour) if s else None


def weather_sources(series: dict[LatLon, HourlySeries]) -> list[str]:
    """Providers behind the forecasts actually used, cached ones included (for attribution)."""
    return sorted({name for s in series.values() for name in s.providers})
