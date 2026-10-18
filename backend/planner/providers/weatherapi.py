"""WeatherAPI.com hourly forecast, normalized into the shared HourlySeries schema.

Verified from WeatherAPI's docs (2026-10-18):
  - forecast.json?key=...&q=<lat>,<lon>&days=N returns forecast.forecastday[].hour[] with
    time_epoch (UTC epoch), wind_mph, gust_mph, precip_in ("Precipitation amount in inches")
    and snow_cm ("Snowfall in centimeters").
  - Free plan: 100K calls/month, 3 forecast days. Starter: 3M/month, 7 days. Bulk (up to 50
    locations per call) needs Pro+, so this client makes one request per location.
  - Quota exhausted: HTTP 403 with error code 2007. Bad or disabled key: 401/2006, 403/2008.

Normalization (documented, conservative where the docs are silent):
  - Units: mph as-is; snow cm -> in (/2.54); precip_in is an hourly amount, i.e. in/hr.
  - Rain: WeatherAPI has no rain/snow split, and its docs don't say whether precip_in includes
    melted snow. All of precip_in is scored as rain, which can only overstate rain, never
    understate it (subtracting snow at an assumed snow-to-liquid ratio could understate it).
  - Time: the docs don't say whether an hour's values cover the hour starting or ending at its
    timestamp. Our schema needs the hour *ending* at H, so each normalized hour takes the max
    of the provider hours stamped H-1 and H. That can only overstate risk, never understate it.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx

from planner.domain.geo import haversine_mi
from planner.domain.models import LatLon
from planner.providers.base import HourlySeries, WeatherFetch

log = logging.getLogger(__name__)

BASE_URL = "https://api.weatherapi.com/v1/forecast.json"
CM_PER_IN = 2.54
RETRY_STATUSES = {500, 502, 503, 504}
# WeatherAPI echoes the coordinates it answered for. Further than this from the cell we asked
# about (a 0.25 deg cell is ~17 mi across) and the forecast isn't for our location.
MAX_LOCATION_OFFSET_MI = 20.0
# Error codes that mean "stop calling for a while": quota spent, or the key is unusable.
QUOTA_CODES = {2007}
KEY_CODES = {1002, 2006, 2008, 2009}


class WeatherApiWeather:
    name = "weatherapi"

    def __init__(
        self,
        client: httpx.Client,
        *,
        api_key: str,
        days: int = 3,
        max_workers: int = 6,
        retries: int = 1,
        backoff_s: float = 0.5,
        now=lambda: datetime.now(UTC),
    ):
        self._client = client
        self._key = api_key
        self._days = days
        self._max_workers = max_workers
        self._retries = retries
        self._backoff_s = backoff_s
        self._now = now

    def hourly(self, cells: list[LatLon], start: datetime, end: datetime) -> WeatherFetch:
        out = WeatherFetch()
        if not cells:
            return out
        t0 = time.perf_counter()
        stop = threading.Event()  # set once the quota is spent, so remaining cells aren't sent
        lock = threading.Lock()
        days = self._days_needed(end)

        def one(cell: LatLon) -> None:
            if stop.is_set():
                return
            series, error, statuses, exhausted_until = self._fetch_cell(cell, days)
            with lock:
                for status in statuses:
                    out.calls.record(status)
                if series is not None:
                    out[cell] = series
                if error:
                    out.errors.append(error)
                if exhausted_until:
                    stop.set()
                    out.quota_exhausted_until = exhausted_until

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(one, cells))
        out.calls.ms = round((time.perf_counter() - t0) * 1000)
        out.errors = list(dict.fromkeys(out.errors))
        fetched_at = self._now()
        for s in out.values():
            s.source, s.fetched_at, s.requested_end = self.name, fetched_at, end
        log.info(
            "weather provider=%s cells=%d ok=%d requests=%d statuses=%s ms=%d",
            self.name,
            len(cells),
            len(out),
            out.calls.requests,
            out.calls.statuses,
            out.calls.ms,
        )
        return out

    def _days_needed(self, end: datetime) -> int:
        """Forecast days to ask for: enough to reach `end`, capped by the plan's horizon.
        Days are local dates at the location, which in the Americas trail UTC by up to a day,
        so ask for one extra."""
        today = self._now().astimezone(UTC).date()
        needed = (end.astimezone(UTC).date() - today).days + 2
        return max(1, min(self._days, needed))

    def _fetch_cell(
        self, cell: LatLon, days: int
    ) -> tuple[HourlySeries | None, str | None, list[str], datetime | None]:
        params = {
            "key": self._key,
            "q": f"{cell.lat:.4f},{cell.lon:.4f}",
            "days": str(days),
            "aqi": "no",
            "alerts": "no",
        }
        statuses: list[str] = []
        reason = "no response"
        for attempt in range(self._retries + 1):
            try:
                response = self._client.get(BASE_URL, params=params)
            except httpx.HTTPError as exc:
                statuses.append("timeout" if isinstance(exc, httpx.TimeoutException) else "error")
                reason = f"request failed ({type(exc).__name__})"
            else:
                statuses.append(str(response.status_code))
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError:
                        return None, "WeatherAPI returned a non-JSON response", statuses, None
                    series = parse_forecast(data)
                    if series is None:
                        return None, "WeatherAPI response had no usable hourly data", statuses, None
                    offset = _location_offset_mi(data, cell)
                    if offset is not None and offset > MAX_LOCATION_OFFSET_MI:
                        return None, "WeatherAPI answered for a different location", statuses, None
                    return series, None, statuses, None
                code, message = _error(response, self._key)
                reason = f"HTTP {response.status_code} (code {code}): {message}"
                if code in QUOTA_CODES:
                    return None, reason, statuses, self._next_month()
                if code in KEY_CODES:
                    # Misconfiguration: stop for an hour rather than fail every request.
                    return None, reason, statuses, self._now() + timedelta(hours=1)
                if response.status_code not in RETRY_STATUSES:
                    return None, reason, statuses, None
            if attempt < self._retries:
                time.sleep(self._backoff_s * 2**attempt)
        return None, reason, statuses, None

    def _next_month(self) -> datetime:
        now = self._now().astimezone(UTC)
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (first + timedelta(days=32)).replace(day=1)


def _error(response: httpx.Response, api_key: str) -> tuple[int | None, str]:
    code, message = None, response.reason_phrase or "error"
    try:
        err = response.json().get("error") or {}
        code = int(err.get("code")) if err.get("code") is not None else None
        message = str(err.get("message") or message)
    except (ValueError, AttributeError, TypeError):
        pass
    if api_key:
        message = message.replace(api_key, "***")
    return code, message[:160]


def _location_offset_mi(data: dict, cell: LatLon) -> float | None:
    """Miles between the cell and the location WeatherAPI answered for (None if absent)."""
    loc = data.get("location") if isinstance(data, dict) else None
    if not isinstance(loc, dict):
        return None
    lat, lon = loc.get("lat"), loc.get("lon")
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lat, lon)):
        return None
    return haversine_mi(cell, LatLon(float(lat), float(lon)))


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    v = float(value)
    return v if v >= 0 and v == v and v != float("inf") else None


def parse_forecast(data: object) -> HourlySeries | None:
    """WeatherAPI forecast JSON -> normalized HourlySeries (see module docstring)."""
    if not isinstance(data, dict):
        return None
    days = (data.get("forecast") or {}).get("forecastday")
    if not isinstance(days, list):
        return None
    raw: dict[int, tuple[float | None, float | None, float | None, float | None]] = {}
    for day in days:
        for hour in (day or {}).get("hour") or []:
            if not isinstance(hour, dict) or not isinstance(hour.get("time_epoch"), int):
                continue
            wind, gust = _num(hour.get("wind_mph")), _num(hour.get("gust_mph"))
            precip, snow_cm = _num(hour.get("precip_in")), _num(hour.get("snow_cm"))
            snow = None if snow_cm is None else snow_cm / CM_PER_IN
            raw[hour["time_epoch"]] = (wind, gust, precip, snow)
    if len(raw) < 2:
        return None
    epochs = sorted(raw)
    first, last = epochs[0], epochs[-1]
    if any(e % 3600 for e in epochs):
        return None  # not on hour boundaries: don't guess an alignment

    def worst(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else max(a, b)

    columns: list[list[float | None]] = [[], [], [], []]
    for h_end in range(first + 3600, last + 3600, 3600):
        prev, cur = raw.get(h_end - 3600), raw.get(h_end)
        for k in range(4):
            columns[k].append(worst(prev[k], cur[k]) if prev and cur else None)
    return HourlySeries(
        start=datetime.fromtimestamp(first + 3600, tz=UTC),
        wind_mph=columns[0],
        gust_mph=columns[1],
        rain_in_hr=columns[2],
        snow_in_hr=columns[3],
    )
