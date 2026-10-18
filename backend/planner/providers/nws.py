"""US National Weather Service (api.weather.gov) raw gridpoint forecasts, normalized into
the shared HourlySeries schema. Used as the fallback provider.

Verified against the live API and its docs (2026-10-18):
  - No key; a descriptive User-Agent is required. The rate limit is not published; a
    rate-limited request "may be retried after the limit clears" (about 5 s).
  - Discovery: GET /points/{lat},{lon} (at most 4 decimals, else a 301) returns
    properties.forecastGridData, e.g. https://api.weather.gov/gridpoints/BOU/63,62.
    Points outside NWS coverage answer 404 "InvalidPoint". /points is cacheable for 24 h.
  - The gridpoint forecast (cacheable for about 1 h, 200-260 KB) has time series of
    {validTime: "<ISO start>/<ISO duration>", value} per layer, with units in `uom`:
      windSpeed, windGust             km/h; one value held over 1-13 h runs
      quantitativePrecipitation       mm, the total over the interval (almost always 6 h)
      snowfallAmount                  mm of snow, the total over the interval (6 h)
  - The hourly text forecast (/forecast/hourly) has no gusts and no precipitation amounts,
    only a probability of precipitation, so it is not used.

Normalization (conservative where the source is coarser than the schema):
  - Wind and gusts: km/h -> mph. A run's value applies to every hour in it. Like WeatherAPI,
    the hour ending at H takes the worse of the values at H-1 and H, so risk is never
    understated.
  - Rain and snow: the schema needs in/hr, but NWS gives multi-hour totals. A total cannot be
    turned into an hourly intensity, so an hour's value is known only when its interval is
    exactly 1 h long, or the interval's total is exactly zero (no precipitation in any of
    its hours). A measurable 6 h total leaves those hours' rain or snow unknown.
    Precipitation is liquid-equivalent and includes melted snow; all of it is scored as rain,
    which can only overstate rain. Probability of precipitation is never used as intensity.
  - Unknown units, values off the hour, or a forecast older than `max_age` -> unknown.
"""

import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from django.core.cache import BaseCache

from planner.domain.geo import haversine_mi
from planner.domain.models import LatLon
from planner.providers.base import HourlySeries, WeatherFetch

log = logging.getLogger(__name__)

BASE_URL = "https://api.weather.gov"
RETRY_STATUSES = {429, 500, 502, 503, 504}
# How far the gridpoint cell may be from the point we asked about. NWS cells are ~2.5 km.
MAX_GRID_OFFSET_MI = 3.0
# Pause after a rate limit that outlasted the retries, so the chain stops asking for a bit.
RATE_LIMIT_PAUSE = timedelta(minutes=1)
MAX_RETRY_AFTER_S = 5.0

SPEED_TO_MPH = {
    "wmoUnit:km_h-1": 1 / 1.609344,
    "wmoUnit:m_s-1": 3600 / 1609.344,
    "wmoUnit:kn": 1.150779448,
}
LENGTH_TO_IN = {"wmoUnit:mm": 1 / 25.4, "wmoUnit:cm": 1 / 2.54, "wmoUnit:m": 1 / 0.0254}

# Areas the NWS forecasts (lat_min, lat_max, lon_min, lon_max): CONUS, Alaska, Hawaii,
# Puerto Rico and the US Virgin Islands, Guam. Boxes are generous; a /points 404 settles the
# edges (e.g. southern Canada inside the CONUS box) and is cached.
US_AREAS = (
    (24.3, 49.5, -125.0, -66.8),
    (51.0, 71.6, -180.0, -129.9),
    (18.8, 22.4, -160.4, -154.7),
    (17.6, 18.6, -67.4, -64.5),
    (13.2, 13.7, 144.6, 145.0),
)

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


@dataclass(slots=True)
class GridForecast:
    """One NWS gridpoint's normalized forecast, plus where that grid cell is."""

    series: HourlySeries
    center: LatLon | None  # centre of the gridpoint polygon, if the response had one


def is_supported(cell: LatLon) -> bool:
    return any(a <= cell.lat <= b and c <= cell.lon <= d for a, b, c, d in US_AREAS)


class NwsWeather:
    name = "nws"

    def __init__(
        self,
        client: httpx.Client,
        cache: BaseCache,
        *,
        user_agent: str,
        max_workers: int = 6,
        retries: int = 2,
        backoff_s: float = 1.0,
        point_ttl_s: int = 24 * 3600,
        grid_ttl_s: int = 3600,
        max_age: timedelta = timedelta(hours=24),
        now=lambda: datetime.now(UTC),
    ):
        if not user_agent.strip():
            raise ValueError("NWS requires a descriptive User-Agent")
        self._client = client
        self._cache = cache
        self._headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
        self._max_workers = max_workers
        self._retries = retries
        self._backoff_s = backoff_s
        self._point_ttl = point_ttl_s
        self._grid_ttl = grid_ttl_s
        self._max_age = max_age
        self._now = now

    def hourly(self, cells: list[LatLon], start: datetime, end: datetime) -> WeatherFetch:
        out = WeatherFetch()
        if not cells:
            return out
        t0 = time.perf_counter()
        lock = threading.Lock()
        stop = threading.Event()  # set when rate-limited past the retries
        cache_hits = {"point": 0, "grid": 0}
        outside = [c for c in cells if not is_supported(c)]
        if outside:
            out.errors.append(f"{len(outside)} cells outside NWS coverage (US only)")
        supported = [c for c in cells if is_supported(c)]

        def note(statuses: list[str], error: str | None, paused: bool) -> None:
            with lock:
                for status in statuses:
                    out.calls.record(status)
                if error:
                    out.errors.append(error)
                if paused:
                    stop.set()
                    out.quota_exhausted_until = self._now() + RATE_LIMIT_PAUSE

        # 1. Point -> gridpoint URL, cached; unsupported points are cached too.
        grid_of: dict[LatLon, str] = {}
        not_covered: list[LatLon] = []

        def resolve(cell: LatLon) -> None:
            if stop.is_set():
                return
            key = _point_key(cell)
            meta = self._cache.get(key)
            if meta is not None:
                with lock:
                    cache_hits["point"] += 1
            else:
                meta, statuses, error, paused = self._fetch_point(cell)
                note(statuses, error, paused)
                if meta is not None:
                    self._cache.set(key, meta, self._point_ttl)
            with lock:
                if meta and meta.get("grid_url"):
                    grid_of[cell] = meta["grid_url"]
                elif meta is not None:
                    not_covered.append(cell)

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(resolve, supported))
        if not_covered:
            out.errors.append(f"{len(not_covered)} cells have no NWS forecast (outside its grids)")

        # 2. Gridpoint forecasts, deduplicated (two cells may share a gridpoint), cached.
        grids: dict[str, GridForecast] = {}

        def forecast(url: str) -> None:
            if stop.is_set():
                return
            key = "nws:grid:" + url.removeprefix(BASE_URL + "/gridpoints/")
            grid = self._cache.get(key)
            if grid is not None:
                with lock:
                    cache_hits["grid"] += 1
            else:
                grid, statuses, error, paused = self._fetch_grid(url)
                note(statuses, error, paused)
                if grid is not None:
                    self._cache.set(key, grid, self._grid_ttl)
            if grid is not None:
                with lock:
                    grids[url] = grid

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(forecast, list(dict.fromkeys(grid_of.values()))))

        fetched_at = self._now()
        for cell, url in grid_of.items():
            grid = grids.get(url)
            if grid is None:
                continue
            if grid.center is not None and haversine_mi(cell, grid.center) > MAX_GRID_OFFSET_MI:
                out.errors.append("gridpoint does not match the requested location")
                continue
            s = grid.series
            out[cell] = HourlySeries(
                start=s.start,
                wind_mph=list(s.wind_mph),
                gust_mph=list(s.gust_mph),
                rain_in_hr=list(s.rain_in_hr),
                snow_in_hr=list(s.snow_in_hr),
                source=self.name,
                fetched_at=s.fetched_at or fetched_at,
                requested_end=end,
            )
        out.calls.ms = round((time.perf_counter() - t0) * 1000)
        out.errors = list(dict.fromkeys(out.errors))
        log.info(
            "weather provider=%s cells=%d ok=%d outside_us=%d requests=%d statuses=%s "
            "cache_hits=%s ms=%d",
            self.name,
            len(cells),
            len(out),
            len(outside),
            out.calls.requests,
            out.calls.statuses,
            cache_hits,
            out.calls.ms,
        )
        return out

    # -- HTTP -----------------------------------------------------------------------------

    def _get(self, url: str) -> tuple[httpx.Response | None, list[str], str, bool]:
        """GET with bounded retries. Returns (response, statuses, failure reason, paused)."""
        statuses: list[str] = []
        reason = "no response"
        for attempt in range(self._retries + 1):
            wait = self._backoff_s * 2**attempt
            try:
                response = self._client.get(url, headers=self._headers)
            except httpx.HTTPError as exc:
                statuses.append("timeout" if isinstance(exc, httpx.TimeoutException) else "error")
                reason = f"request failed ({type(exc).__name__})"
            else:
                statuses.append(str(response.status_code))
                if response.status_code not in RETRY_STATUSES:
                    return response, statuses, "", False
                reason = f"HTTP {response.status_code}: {_detail(response)}"
                wait = max(wait, _retry_after(response))
            if attempt < self._retries:
                time.sleep(wait)
        return None, statuses, reason, statuses[-1] == "429"

    def _fetch_point(self, cell: LatLon) -> tuple[dict | None, list[str], str | None, bool]:
        response, statuses, reason, paused = self._get(f"{BASE_URL}/points/{_coords(cell)}")
        if response is None:
            return None, statuses, f"points: {reason}", paused
        if response.status_code == 404 and _problem(response).endswith("/InvalidPoint"):
            # Outside NWS coverage: remember that, so the point isn't asked again for a day.
            return {"grid_url": None}, statuses, None, False
        if response.status_code != 200:
            return (
                None,
                statuses,
                f"points: HTTP {response.status_code}: {_detail(response)}",
                False,
            )
        try:
            url = (response.json().get("properties") or {}).get("forecastGridData")
        except (ValueError, AttributeError):
            return None, statuses, "points: malformed response", False
        if not isinstance(url, str) or not url.startswith(BASE_URL + "/gridpoints/"):
            # Never follow a grid URL to another host.
            return None, statuses, "points: response had no usable forecastGridData", False
        return {"grid_url": url}, statuses, None, False

    def _fetch_grid(self, url: str) -> tuple[GridForecast | None, list[str], str | None, bool]:
        response, statuses, reason, paused = self._get(url)
        if response is None:
            return None, statuses, f"gridpoints: {reason}", paused
        if response.status_code != 200:
            return (
                None,
                statuses,
                f"gridpoints: HTTP {response.status_code}: {_detail(response)}",
                False,
            )
        try:
            data = response.json()
        except ValueError:
            return None, statuses, "gridpoints: non-JSON response", False
        series, problem = parse_gridpoint(data, now=self._now(), max_age=self._max_age)
        if series is None:
            return None, statuses, f"gridpoints: {problem}", False
        series.fetched_at = self._now()
        return GridForecast(series, _polygon_center(data)), statuses, None, False


# -- parsing ------------------------------------------------------------------------------


def parse_gridpoint(
    data: object, *, now: datetime, max_age: timedelta = timedelta(hours=24)
) -> tuple[HourlySeries | None, str]:
    """NWS gridpoint JSON -> (normalized HourlySeries, "") or (None, why it was rejected)."""
    if not isinstance(data, dict) or not isinstance(data.get("properties"), dict):
        return None, "malformed response"
    props = data["properties"]
    updated = _parse_time(props.get("updateTime"))
    if updated is None:
        return None, "no updateTime"
    if now - updated > max_age:
        return None, f"stale forecast (updated {updated.isoformat(timespec='minutes')})"

    wind = _hourly_levels(props.get("windSpeed"), SPEED_TO_MPH)
    gust = _hourly_levels(props.get("windGust"), SPEED_TO_MPH)
    rain = _hourly_amounts(props.get("quantitativePrecipitation"), LENGTH_TO_IN)
    snow = _hourly_amounts(props.get("snowfallAmount"), LENGTH_TO_IN)
    hours = set(wind) | set(gust)
    if not hours:
        return None, "no wind data"
    first, last = min(hours), max(hours)

    def worst(values: dict[datetime, float], h_end: datetime) -> float | None:
        a, b = values.get(h_end - timedelta(hours=1)), values.get(h_end)
        return None if a is None or b is None else max(a, b)

    columns: list[list[float | None]] = [[], [], [], []]
    h_end = first + timedelta(hours=1)
    while h_end <= last:
        begin = h_end - timedelta(hours=1)  # the hour [begin, h_end) this index covers
        columns[0].append(worst(wind, h_end))
        columns[1].append(worst(gust, h_end))
        columns[2].append(rain.get(begin))
        columns[3].append(snow.get(begin))
        h_end += timedelta(hours=1)
    if not columns[0]:
        return None, "too little data"
    return (
        HourlySeries(
            start=first + timedelta(hours=1),
            wind_mph=columns[0],
            gust_mph=columns[1],
            rain_in_hr=columns[2],
            snow_in_hr=columns[3],
        ),
        "",
    )


def _intervals(layer: object, units: dict[str, float]):
    """(start, hours, value in target units) for each well-formed entry of a layer."""
    if not isinstance(layer, dict):
        return
    factor = units.get(layer.get("uom"))
    if factor is None:
        return  # unknown or missing unit: never guess
    for entry in layer.get("values") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("validTime"), str):
            continue
        start_s, _, duration_s = entry["validTime"].partition("/")
        start, hours = _parse_time(start_s), _hours(duration_s)
        value = entry.get("value")
        if start is None or hours is None or start.minute or start.second or start.microsecond:
            continue  # not on an hour boundary: don't guess an alignment
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        yield start, hours, value * factor


def _hourly_levels(layer: object, units: dict[str, float]) -> dict[datetime, float]:
    """A held value (wind) applies to every hour of its interval, keyed by hour start."""
    out: dict[datetime, float] = {}
    for start, hours, value in _intervals(layer, units):
        for h in range(hours):
            out[start + timedelta(hours=h)] = value
    return out


def _hourly_amounts(layer: object, units: dict[str, float]) -> dict[datetime, float]:
    """An interval total (rain, snow) gives an hourly rate only if it is 1 h long, or zero."""
    out: dict[datetime, float] = {}
    for start, hours, value in _intervals(layer, units):
        if hours == 1 or value == 0:
            for h in range(hours):
                out[start + timedelta(hours=h)] = 0.0 if value == 0 else value
    return out


def _hours(duration: str) -> int | None:
    m = _DURATION.match(duration)
    if not m or not any(m.groups()):
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    if minutes or seconds:
        return None
    total = days * 24 + hours
    return total if total > 0 else None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else None


def _coords(cell: LatLon) -> str:
    """At most 4 decimals, without trailing zeros (NWS redirects anything more precise)."""

    def fmt(v: float) -> str:
        return f"{v:.4f}".rstrip("0").rstrip(".")

    return f"{fmt(cell.lat)},{fmt(cell.lon)}"


def _point_key(cell: LatLon) -> str:
    return f"nws:point:{cell.lat:.4f}:{cell.lon:.4f}"


def _polygon_center(data: dict) -> LatLon | None:
    """Centre of the gridpoint's GeoJSON polygon ([[[lon, lat], ...]]), if well-formed."""
    try:
        ring = data["geometry"]["coordinates"][0]
        pts = [(float(lat), float(lon)) for lon, lat in ring[:-1] or ring]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if not pts:
        return None
    return LatLon(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _problem(response: httpx.Response) -> str:
    try:
        return str(response.json().get("type") or "")
    except (ValueError, AttributeError):
        return ""


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(float(response.headers.get("Retry-After", 0)), MAX_RETRY_AFTER_S)
    except ValueError:
        return 0.0


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        text = str(body.get("title") or body.get("detail") or response.reason_phrase)
    except (ValueError, AttributeError):
        text = response.reason_phrase or "error"
    return text[:160]
