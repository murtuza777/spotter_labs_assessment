"""Open-Meteo hourly forecast for many locations, batched and retried.

Units requested match the risk rules directly: mph for wind, inches for rain and snowfall.
Gusts, rain, showers and snowfall are "preceding hour" values (see domain/timebucket.py).
"""

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx

from planner.domain.models import LatLon
from planner.providers.base import HourlySeries

log = logging.getLogger(__name__)

HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class WeatherFetch(dict):
    """Series per cell (a plain dict to callers), plus why any batch failed, so the API can
    tell users "the weather service refused the request" instead of silently showing gaps."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []


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
        out = WeatherFetch()
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for result, error in pool.map(lambda b: self._fetch_batch(b, start, end), batches):
                out.update(result)
                if error:
                    out.errors.append(error)
        return out

    def _fetch_batch(
        self, cells: list[LatLon], start: datetime, end: datetime
    ) -> tuple[dict[LatLon, HourlySeries], str | None]:
        """Series for one batch, and the failure reason if it couldn't be fetched."""
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
        reason = "no response"
        for attempt in range(self._retries + 1):
            try:
                response = self._client.get(self._base_url, params=params)
            except httpx.HTTPError as exc:
                response = None
                reason = f"request failed ({type(exc).__name__})"
            if response is not None and response.status_code == 200:
                try:
                    return parse_response(response.json(), cells), None
                except ValueError:
                    return {}, "Open-Meteo returned a non-JSON response"
            if response is not None:
                reason = f"HTTP {response.status_code}: {_reason(response)}"
                if response.status_code not in RETRY_STATUSES:
                    log.warning("Open-Meteo batch of %d failed: %s", len(cells), reason)
                    return {}, reason
            log.warning(
                "Open-Meteo batch of %d attempt %d failed: %s", len(cells), attempt + 1, reason
            )
            if attempt < self._retries:
                time.sleep(self._backoff_s * 2**attempt)
        log.warning(
            "Open-Meteo batch of %d gave up after %d retries: %s", len(cells), self._retries, reason
        )
        return {}, reason


def _reason(response: httpx.Response) -> str:
    """Open-Meteo puts a human-readable cause in {"error": true, "reason": "..."}."""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("reason"):
            return str(body["reason"])[:160]
    except ValueError:
        pass
    return response.reason_phrase or "error"


def parse_response(data: object, cells: list[LatLon]) -> dict[LatLon, HourlySeries]:
    """Open-Meteo returns one object per requested location, in request order.

    Vendor data is validated rather than trusted: a location whose time axis is missing or
    not hourly is dropped, and every individual reading that is not a finite, non-negative
    number becomes None ("unknown"), so it can never be scored as calm or as No Travel.
    """
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        log.warning("Open-Meteo returned %s instead of a list", type(data).__name__)
        return {}
    out: dict[LatLon, HourlySeries] = {}
    for cell, loc in zip(cells, data, strict=False):
        hourly = loc.get("hourly") if isinstance(loc, dict) else None
        if not isinstance(hourly, dict):
            continue
        times = hourly.get("time")
        if not _is_hourly_axis(times):
            log.warning("Open-Meteo time axis invalid for %s", cell)
            continue
        n = len(times)
        rain = _readings(hourly.get("rain"), n)
        showers = _readings(hourly.get("showers"), n)
        out[cell] = HourlySeries(
            start=datetime.fromtimestamp(times[0], tz=UTC),
            wind_mph=_readings(hourly.get("wind_speed_10m"), n),
            gust_mph=_readings(hourly.get("wind_gusts_10m"), n),
            # Liquid precipitation only: large-scale rain plus convective showers. If either
            # part is missing the total is unknown, not "whatever part we have".
            rain_in_hr=[
                None if r is None or s is None else r + s
                for r, s in zip(rain, showers, strict=True)
            ],
            snow_in_hr=_readings(hourly.get("snowfall"), n),
        )
    return out


def _is_hourly_axis(times: object) -> bool:
    if not isinstance(times, list) or not times:
        return False
    if not all(isinstance(t, int | float) and not isinstance(t, bool) for t in times):
        return False
    return all(b - a == 3600 for a, b in zip(times, times[1:], strict=False))


def _readings(values: object, n: int) -> list[float | None]:
    """Exactly `n` readings; anything missing or invalid is None."""
    raw = values if isinstance(values, list) else []
    return [_valid(raw[i]) if i < len(raw) else None for i in range(n)]


def _valid(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)
