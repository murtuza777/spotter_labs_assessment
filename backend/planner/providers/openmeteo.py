"""Open-Meteo hourly forecast for many locations, batched and retried.

Units requested match the risk rules directly: mph for wind, inches for rain and snowfall.
Gusts, rain, showers and snowfall are "preceding hour" values, i.e. already in the normalized
HourlySeries convention (see providers/base.py and domain/timebucket.py).

Two endpoints, identical requests and responses:
  - free:     api.open-meteo.com, non-commercial, rate-limited per IP (10,000 calls/day). On
              hosts with shared outbound IPs (Render free) other tenants can exhaust it.
  - customer: customer-api.open-meteo.com with &apikey=..., used when an API key is set.
"""

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx

from planner.domain.models import LatLon
from planner.providers.base import HourlySeries, WeatherFetch

log = logging.getLogger(__name__)

HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
FREE_URL = "https://api.open-meteo.com/v1/forecast"
CUSTOMER_URL = "https://customer-api.open-meteo.com/v1/forecast"
# Transient: worth a bounded retry. A 429 is only retried when it is a per-minute limit.
RETRY_STATUSES = {500, 502, 503, 504}


class OpenMeteoWeather:
    name = "open-meteo"

    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str | None = None,
        api_key: str = "",
        model: str = "gfs_seamless",
        batch_size: int = 25,
        max_workers: int = 3,
        retries: int = 2,
        backoff_s: float = 1.0,
        now=lambda: datetime.now(UTC),
    ):
        self._client = client
        self._api_key = api_key
        self._base_url = base_url or (CUSTOMER_URL if api_key else FREE_URL)
        self._model = model
        self._batch_size = batch_size
        self._max_workers = max_workers
        self._retries = retries
        self._backoff_s = backoff_s
        self._now = now

    @property
    def endpoint(self) -> str:
        return "customer" if self._api_key else "free"

    def hourly(self, cells: list[LatLon], start: datetime, end: datetime) -> WeatherFetch:
        out = WeatherFetch()
        if not cells:
            return out
        t0 = time.perf_counter()
        batches = [cells[i : i + self._batch_size] for i in range(0, len(cells), self._batch_size)]
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            results = list(pool.map(lambda b: self._fetch_batch(b, start, end), batches))
        for series, error, statuses, exhausted_until in results:
            out.update(series)
            for status in statuses:
                out.calls.record(status)
            if error:
                out.errors.append(error)
            if exhausted_until and (
                out.quota_exhausted_until is None or exhausted_until > out.quota_exhausted_until
            ):
                out.quota_exhausted_until = exhausted_until
        out.calls.ms = round((time.perf_counter() - t0) * 1000)
        fetched_at = self._now()
        for s in out.values():
            s.source, s.fetched_at, s.requested_end = self.name, fetched_at, end
        return out

    def _fetch_batch(
        self, cells: list[LatLon], start: datetime, end: datetime
    ) -> tuple[dict[LatLon, HourlySeries], str | None, list[str], datetime | None]:
        """(series, failure reason, status per attempt, quota-exhausted-until) for one batch."""
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
        if self._api_key:
            params["apikey"] = self._api_key
        statuses: list[str] = []
        reason = "no response"
        for attempt in range(self._retries + 1):
            t = time.perf_counter()
            try:
                response = self._client.get(self._base_url, params=params)
            except httpx.HTTPError as exc:
                statuses.append("timeout" if isinstance(exc, httpx.TimeoutException) else "error")
                reason = f"request failed ({type(exc).__name__})"
                retry = True
            else:
                statuses.append(str(response.status_code))
                if response.status_code == 200:
                    log.info(
                        "weather provider=%s endpoint=%s cells=%d status=200 ms=%d",
                        self.name,
                        self.endpoint,
                        len(cells),
                        (time.perf_counter() - t) * 1000,
                    )
                    try:
                        return parse_response(response.json(), cells), None, statuses, None
                    except ValueError:
                        return {}, "Open-Meteo returned a non-JSON response", statuses, None
                reason = f"HTTP {response.status_code}: {_reason(response, self._api_key)}"
                exhausted_until = self._quota_exhausted_until(response.status_code, reason)
                if exhausted_until:
                    log.warning(
                        "weather provider=%s endpoint=%s quota exhausted until %s: %s",
                        self.name,
                        self.endpoint,
                        exhausted_until.isoformat(),
                        reason,
                    )
                    return {}, reason, statuses, exhausted_until
                retry = response.status_code in RETRY_STATUSES or (
                    response.status_code == 429 and "minutely" in reason.lower()
                )
            log.warning(
                "weather provider=%s endpoint=%s cells=%d attempt=%d failed: %s",
                self.name,
                self.endpoint,
                len(cells),
                attempt + 1,
                reason,
            )
            if not retry:
                break
            if attempt < self._retries:
                time.sleep(self._backoff_s * 2**attempt)
        return {}, reason, statuses, None

    def _quota_exhausted_until(self, status: int, reason: str) -> datetime | None:
        """When a 429 means the daily/hourly/monthly budget is spent, when it resets.

        Retrying these only burns more of somebody's quota, so the provider is skipped until
        then (the caller falls back to the next provider)."""
        if status != 429:
            return None
        now = self._now().astimezone(UTC)
        text = reason.lower()
        if "daily" in text:
            return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        if "hourly" in text:
            return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        if "monthly" in text:
            return now + timedelta(hours=6)  # re-check a few times a day, not every request
        return None


def _reason(response: httpx.Response, api_key: str = "") -> str:
    """Open-Meteo puts a human-readable cause in {"error": true, "reason": "..."}."""
    text = response.reason_phrase or "error"
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("reason"):
            text = str(body["reason"])
    except ValueError:
        pass
    if api_key:
        text = text.replace(api_key, "***")
    return text[:160]


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
