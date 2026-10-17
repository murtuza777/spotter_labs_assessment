"""Open-Meteo hourly forecast for many locations, batched and retried.

Units requested match the risk rules directly: mph for wind, inches for rain and snowfall.
Gusts, rain, showers and snowfall are "preceding hour" values (see domain/timebucket.py).
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx

from planner.domain.models import LatLon
from planner.providers.base import HourlySeries

log = logging.getLogger(__name__)

HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class OpenMeteoWeather:
    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        model: str = "gfs_seamless",
        batch_size: int = 25,
        max_workers: int = 3,
        retries: int = 3,
        backoff_s: float = 1.0,
    ):
        self._client = client
        self._base_url = base_url
        self._model = model
        self._batch_size = batch_size
        self._max_workers = max_workers
        self._retries = retries
        self._backoff_s = backoff_s

    def hourly(
        self, cells: list[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlySeries]:
        if not cells:
            return {}
        batches = [cells[i : i + self._batch_size] for i in range(0, len(cells), self._batch_size)]
        out: dict[LatLon, HourlySeries] = {}
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for result in pool.map(lambda b: self._fetch_batch(b, start, end), batches):
                out.update(result)
        return out

    def _fetch_batch(
        self, cells: list[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlySeries]:
        params = {
            "latitude": ",".join(f"{c.lat:g}" for c in cells),
            "longitude": ",".join(f"{c.lon:g}" for c in cells),
            "hourly": HOURLY_VARS,
            "models": self._model,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "timeformat": "unixtime",
            "start_hour": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"),
            "end_hour": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"),
        }
        for attempt in range(self._retries + 1):
            try:
                response = self._client.get(self._base_url, params=params)
            except httpx.HTTPError as exc:
                log.warning("Open-Meteo batch of %d failed: %s", len(cells), type(exc).__name__)
                response = None
            if response is not None and response.status_code == 200:
                return parse_response(response.json(), cells)
            status = response.status_code if response is not None else None
            if status is not None and status not in RETRY_STATUSES:
                log.warning("Open-Meteo HTTP %s: %s", status, response.text[:200])
                return {}
            if attempt < self._retries:
                time.sleep(self._backoff_s * 2**attempt)
        log.warning("Open-Meteo batch of %d gave up after %d retries", len(cells), self._retries)
        return {}


def parse_response(data: dict | list, cells: list[LatLon]) -> dict[LatLon, HourlySeries]:
    """Open-Meteo returns one object per requested location, in request order."""
    locations = data if isinstance(data, list) else [data]
    out: dict[LatLon, HourlySeries] = {}
    for cell, loc in zip(cells, locations, strict=False):
        hourly = loc.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            continue
        rain = hourly.get("rain") or []
        showers = hourly.get("showers") or []
        out[cell] = HourlySeries(
            start=datetime.fromtimestamp(times[0], tz=UTC),
            wind_mph=list(hourly.get("wind_speed_10m") or []),
            gust_mph=list(hourly.get("wind_gusts_10m") or []),
            # Liquid precipitation only: large-scale rain plus convective showers.
            rain_in_hr=[_add(r, s) for r, s in zip(rain, showers, strict=False)],
            snow_in_hr=list(hourly.get("snowfall") or []),
        )
    return out


def _add(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)
