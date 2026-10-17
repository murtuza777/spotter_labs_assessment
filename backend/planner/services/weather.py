"""Weather lookups on the model grid, cached per cell."""

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from django.core.cache import BaseCache

from planner.domain.geo import snap
from planner.domain.models import LatLon, WeatherSample
from planner.providers.base import HourlySeries, WeatherProvider

log = logging.getLogger(__name__)

# Fetch at least this far ahead so one cached series serves the plan and the 48 h heatmap.
MIN_FETCH_HOURS = 72
MAX_FORECAST_HOURS = 16 * 24


@dataclass(frozen=True, slots=True)
class WeatherStats:
    cells: int
    cached: int
    fetched: int
    failed: int
    ms: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class WeatherService:
    def __init__(
        self,
        provider: WeatherProvider,
        cache: BaseCache,
        *,
        grid_deg: float,
        ttl_s: int,
        model: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._provider = provider
        self._cache = cache
        self._grid = grid_deg
        self._ttl = ttl_s
        self._model = model
        self._now = now

    @property
    def grid_deg(self) -> float:
        return self._grid

    def cell_for(self, point: LatLon) -> LatLon:
        return LatLon(snap(point.lat, self._grid), snap(point.lon, self._grid))

    def series_for(
        self, cells: Iterable[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlySeries]:
        """Hourly series covering [start, end] for each cell that could be fetched."""
        return self.series_with_stats(cells, start, end)[0]

    def series_with_stats(
        self, cells: Iterable[LatLon], start: datetime, end: datetime
    ) -> tuple[dict[LatLon, HourlySeries], "WeatherStats"]:
        """Like `series_for`, plus how many cells were cached, fetched or failed.

        Cells that fail are not cached, so the next request retries them.
        """
        t0 = time.perf_counter()
        wanted = list(dict.fromkeys(cells))
        found: dict[LatLon, HourlySeries] = {}
        keys = {cell: self._key(cell) for cell in wanted}
        cached = self._cache.get_many(list(keys.values()))
        missing = []
        for cell in wanted:
            series = cached.get(keys[cell])
            if series is not None and series.covers(start, end):
                found[cell] = series
            else:
                missing.append(cell)

        fetched: dict[LatLon, HourlySeries] = {}
        if missing:
            fetch_start, fetch_end = self._fetch_window(start, end)
            fetched = self._provider.hourly(missing, fetch_start, fetch_end)
            self._cache.set_many({keys[c]: s for c, s in fetched.items()}, timeout=self._ttl)
            found.update(fetched)
        stats = WeatherStats(
            cells=len(wanted),
            cached=len(wanted) - len(missing),
            fetched=len(fetched),
            failed=len(missing) - len(fetched),
            ms=round((time.perf_counter() - t0) * 1000),
        )
        log.info(
            "weather cells=%d cached=%d fetched=%d failed=%d ms=%d",
            stats.cells,
            stats.cached,
            stats.fetched,
            stats.failed,
            stats.ms,
        )
        return found, stats

    def _fetch_window(self, start: datetime, end: datetime) -> tuple[datetime, datetime]:
        now_hour = self._now().astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        fetch_start = min(start, now_hour)
        fetch_end = max(end, now_hour + timedelta(hours=MIN_FETCH_HOURS))
        return fetch_start, min(fetch_end, now_hour + timedelta(hours=MAX_FORECAST_HOURS))

    def _key(self, cell: LatLon) -> str:
        return f"wx:{self._model}:{cell.lat:.3f}:{cell.lon:.3f}"


def sample(
    series: dict[LatLon, HourlySeries], cell: LatLon, hour: datetime
) -> WeatherSample | None:
    s = series.get(cell)
    return s.at(hour) if s else None
