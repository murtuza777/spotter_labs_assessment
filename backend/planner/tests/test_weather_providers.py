"""Weather provider abstraction: normalization, failure handling, fallback chain, caching."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from planner.domain.models import LatLon
from planner.domain.timebucket import forecast_hour_for
from planner.providers.base import HourlySeries, WeatherFetch
from planner.providers.openmeteo import CUSTOMER_URL, FREE_URL, OpenMeteoWeather
from planner.providers.weatherapi import BASE_URL as WA_URL
from planner.providers.weatherapi import WeatherApiWeather, parse_forecast
from planner.services.weather import WeatherService

NOW = datetime(2026, 10, 18, 12, 10, tzinfo=UTC)
T0 = int(datetime(2026, 10, 18, 12, tzinfo=UTC).timestamp())
A, B, C = LatLon(40.0, -105.0), LatLon(41.0, -106.0), LatLon(42.0, -107.0)


def _clock():
    return NOW


# --- WeatherAPI.com normalization ---------------------------------------------------------


def _wa_hour(h: int, *, wind=10.0, gust=20.0, precip=0.0, snow_cm=0.0, **extra) -> dict:
    hour = {
        "time_epoch": T0 + h * 3600,
        "wind_mph": wind,
        "gust_mph": gust,
        "precip_in": precip,
        "snow_cm": snow_cm,
    }
    hour.update(extra)
    return hour


def _wa_body(hours: list[dict]) -> dict:
    return {"location": {"lat": 40, "lon": -105}, "forecast": {"forecastday": [{"hour": hours}]}}


def test_weatherapi_units_and_conservative_rain() -> None:
    body = _wa_body([_wa_hour(0, precip=0.3, snow_cm=2.54), _wa_hour(1, precip=0.3, snow_cm=2.54)])
    s = parse_forecast(body)
    assert s.start == datetime(2026, 10, 18, 13, tzinfo=UTC)  # hour ending 13:00
    sample = s.at(s.start)
    assert sample.snow_in_hr == pytest.approx(1.0)  # 2.54 cm -> 1 in
    # No rain/snow split: all precipitation is scored as rain (can only overstate rain risk).
    assert sample.rain_in_hr == pytest.approx(0.3)
    assert (sample.wind_mph, sample.gust_mph) == (10.0, 20.0)


def test_weatherapi_alignment_takes_the_worse_neighbouring_hour() -> None:
    # Docs don't say whether an hour's value covers the hour before or after its stamp, so the
    # normalized hour ending at H uses max(stamp H-1, stamp H): never understates risk.
    s = parse_forecast(_wa_body([_wa_hour(0, gust=20), _wa_hour(1, gust=48), _wa_hour(2, gust=30)]))
    gusts = [s.at(s.start + timedelta(hours=i)).gust_mph for i in range(2)]
    assert gusts == [48, 48]


def test_weatherapi_missing_or_invalid_values_are_unknown_not_zero() -> None:
    hours = [
        _wa_hour(0),
        _wa_hour(1, gust=None),
        _wa_hour(2),
        _wa_hour(3, snow_cm="x"),
        _wa_hour(4),
    ]
    s = parse_forecast(_wa_body(hours))
    known = [s.at(s.start + timedelta(hours=i)) is not None for i in range(4)]
    # Hours ending 13:00 and 14:00 touch the missing gust; 15:00 and 16:00 touch the bad snow.
    assert known == [False, False, False, False]
    s2 = parse_forecast(_wa_body([_wa_hour(0), _wa_hour(1, precip=-1), _wa_hour(2), _wa_hour(3)]))
    assert [s2.at(s2.start + timedelta(hours=i)) is not None for i in range(3)] == [
        False,
        False,
        True,
    ]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "oops",
        {},
        {"forecast": {"forecastday": "x"}},
        _wa_body([_wa_hour(0)]),  # a single hour can't form an hour-ending series
        _wa_body([{**_wa_hour(0), "time_epoch": T0 + 1800}, _wa_hour(1)]),  # off the hour
    ],
)
def test_weatherapi_malformed_payloads(payload) -> None:
    assert parse_forecast(payload) is None


def test_weatherapi_timestamp_alignment_with_eta_rule() -> None:
    # A truck passing at 14:20 uses the forecast hour ending 15:00 (round up), which for
    # WeatherAPI is max(stamp 14:00, stamp 15:00).
    hours = [_wa_hour(h, gust=g) for h, g in enumerate([10, 11, 30, 44, 12])]  # 12:00..16:00
    s = parse_forecast(_wa_body(hours))
    hour = forecast_hour_for(datetime(2026, 10, 18, 14, 20, tzinfo=UTC))
    assert hour == datetime(2026, 10, 18, 15, tzinfo=UTC)
    assert s.at(hour).gust_mph == 44  # max(30 @ 14:00, 44 @ 15:00)


# --- WeatherAPI.com client ------------------------------------------------------------------


def _wa_echo(hours: list[dict]):
    """A respx side effect answering for the coordinates asked about, as WeatherAPI does."""

    def answer(request: httpx.Request) -> httpx.Response:
        lat, lon = (float(v) for v in request.url.params["q"].split(","))
        body = _wa_body(hours)
        body["location"] = {"lat": round(lat, 2), "lon": round(lon, 2)}
        return httpx.Response(200, json=body)

    return answer


def _wa(**kw) -> WeatherApiWeather:
    return WeatherApiWeather(httpx.Client(), api_key="SECRETKEY", backoff_s=0, now=_clock, **kw)


@respx.mock
def test_weatherapi_one_request_per_cell_with_plan_horizon() -> None:
    route = respx.get(WA_URL).mock(side_effect=_wa_echo([_wa_hour(h) for h in range(5)]))
    out = _wa(days=3).hourly([A, B], NOW, NOW + timedelta(days=7))
    assert set(out) == {A, B}
    assert route.call_count == 2 and out.calls.requests == 2 and out.calls.statuses == {"200": 2}
    params = route.calls[0].request.url.params
    assert params["days"] == "3"  # capped by the free plan, not the 7 days asked for
    assert params["q"] in {"40.0000,-105.0000", "41.0000,-106.0000"}
    series = out[A]
    assert series.source == "weatherapi" and series.fetched_at == NOW
    assert series.requested_end == NOW + timedelta(days=7)


@pytest.mark.parametrize(("days", "hours", "expected"), [(7, 72, 5), (7, 1, 2), (3, 72, 3)])
def test_weatherapi_day_count_allows_for_local_dates(days, hours, expected) -> None:
    # Forecast days are local dates; US evenings are already the next day in UTC.
    assert _wa(days=days)._days_needed(NOW + timedelta(hours=hours)) == expected


@respx.mock
def test_weatherapi_quota_exhausted_stops_and_opens_breaker() -> None:
    route = respx.get(WA_URL).mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {"code": 2007, "message": "API key has exceeded calls per month quota."}
            },
        )
    )
    out = _wa(max_workers=1).hourly([A, B, C], NOW, NOW)
    assert dict(out) == {}
    assert route.call_count == 1  # remaining cells are not sent once the quota is spent
    assert out.quota_exhausted_until == datetime(2026, 11, 1, tzinfo=UTC)
    assert out.errors == ["HTTP 403 (code 2007): API key has exceeded calls per month quota."]


@respx.mock
def test_weatherapi_bad_key_backs_off_and_never_echoes_the_key() -> None:
    respx.get(WA_URL).mock(
        return_value=httpx.Response(
            401, json={"error": {"code": 2006, "message": "API key SECRETKEY is invalid."}}
        )
    )
    out = _wa(max_workers=1).hourly([A], NOW, NOW)
    assert out.quota_exhausted_until == NOW + timedelta(hours=1)
    assert "SECRETKEY" not in out.errors[0] and "***" in out.errors[0]


@respx.mock
def test_weatherapi_retries_5xx_and_timeouts_boundedly() -> None:
    route = respx.get(WA_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=_wa_body([_wa_hour(h) for h in range(3)])),
            httpx.ConnectTimeout("slow"),
            httpx.ConnectTimeout("slow"),
        ]
    )
    out = _wa(max_workers=1, retries=1).hourly([A, B], NOW, NOW)
    assert set(out) == {A}
    assert route.call_count == 4  # 2 attempts per cell, no more
    assert out.calls.statuses == {"503": 1, "200": 1, "timeout": 2}
    assert out.errors == ["request failed (ConnectTimeout)"]


@respx.mock
def test_weatherapi_unknown_location_is_not_retried() -> None:
    route = respx.get(WA_URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"code": 1006, "message": "No matching location found."}}
        )
    )
    out = _wa(max_workers=1).hourly([A], NOW, NOW)
    assert route.call_count == 1 and out.quota_exhausted_until is None


# --- Open-Meteo client ----------------------------------------------------------------------


def _om_body(n: int) -> list[dict]:
    hourly = {
        "time": [T0, T0 + 3600],
        "wind_speed_10m": [5, 6],
        "wind_gusts_10m": [10, 11],
        "rain": [0, 0.1],
        "showers": [0, 0.05],
        "snowfall": [0, 0],
    }
    return [{"hourly": hourly} for _ in range(n)]


@respx.mock
def test_open_meteo_customer_endpoint_with_key() -> None:
    route = respx.get(CUSTOMER_URL).mock(return_value=httpx.Response(200, json=_om_body(2)))
    om = OpenMeteoWeather(httpx.Client(), api_key="PAIDKEY", backoff_s=0, now=_clock)
    out = om.hourly([A, B], NOW, NOW + timedelta(hours=1))
    assert set(out) == {A, B} and om.endpoint == "customer"
    assert route.calls[0].request.url.params["apikey"] == "PAIDKEY"
    assert out[A].source == "open-meteo" and out[A].fetched_at == NOW


def test_open_meteo_free_endpoint_without_key() -> None:
    om = OpenMeteoWeather(httpx.Client(), now=_clock)
    assert om._base_url == FREE_URL and om.endpoint == "free"


@respx.mock
def test_open_meteo_daily_quota_is_not_retried_and_opens_breaker() -> None:
    # The production failure (2026-10-18): Render's shared IP hit the free daily cap.
    route = respx.get(FREE_URL).mock(
        return_value=httpx.Response(
            429,
            json={
                "error": True,
                "reason": "Daily API request limit exceeded. Please try again tomorrow.",
            },
        )
    )
    om = OpenMeteoWeather(httpx.Client(), batch_size=1, max_workers=1, backoff_s=0, now=_clock)
    out = om.hourly([A, B], NOW, NOW)
    assert route.call_count == 2  # one per batch, no retries
    assert out.quota_exhausted_until == datetime(2026, 10, 19, tzinfo=UTC)  # next UTC midnight
    assert out.calls.statuses == {"429": 2}


@respx.mock
def test_open_meteo_minutely_limit_is_retried() -> None:
    route = respx.get(FREE_URL).mock(
        side_effect=[
            httpx.Response(
                429, json={"error": True, "reason": "Minutely API request limit exceeded."}
            ),
            httpx.Response(200, json=_om_body(1)),
        ]
    )
    out = OpenMeteoWeather(httpx.Client(), backoff_s=0, now=_clock).hourly([A], NOW, NOW)
    assert set(out) == {A} and route.call_count == 2 and out.quota_exhausted_until is None


@respx.mock
def test_open_meteo_error_reason_never_echoes_the_key() -> None:
    respx.get(CUSTOMER_URL).mock(
        return_value=httpx.Response(400, json={"error": True, "reason": "apikey PAIDKEY not valid"})
    )
    out = OpenMeteoWeather(httpx.Client(), api_key="PAIDKEY", now=_clock).hourly([A], NOW, NOW)
    assert out.errors == ["HTTP 400: apikey *** not valid"]


# --- The provider chain ---------------------------------------------------------------------


def _series(source: str, *, gust: float = 12.0, hours: int = 96, fetched_at=NOW) -> HourlySeries:
    start = NOW.replace(minute=0)
    return HourlySeries(
        start=start,
        wind_mph=[5.0] * hours,
        gust_mph=[gust] * hours,
        rain_in_hr=[0.0] * hours,
        snow_in_hr=[0.0] * hours,
        source=source,
        fetched_at=fetched_at,
        requested_end=start + timedelta(hours=hours - 1),
    )


class Fake:
    """A provider that serves some cells, fails others, and can report a spent quota."""

    def __init__(self, name, serves=(), *, exhausted_until=None, error=None):
        self.name = name
        self.serves = set(serves)
        self.exhausted_until = exhausted_until
        self.error = error
        self.calls: list[list[LatLon]] = []

    def hourly(self, cells, start, end):
        self.calls.append(list(cells))
        out = WeatherFetch()
        for cell in cells:
            out.calls.record("200" if cell in self.serves else "429")
            if cell in self.serves:
                out[cell] = _series(self.name)
        if self.error:
            out.errors.append(self.error)
        out.quota_exhausted_until = self.exhausted_until
        return out


def _svc(*providers, now=_clock, ttl=3600) -> WeatherService:
    return WeatherService(list(providers), cache, grid_deg=0.25, ttl_s=ttl, model="t", now=now)


def test_fallback_only_gets_the_cells_the_primary_missed() -> None:
    primary = Fake("open-meteo", serves={A}, error="HTTP 503: busy")
    fallback = Fake("weatherapi", serves={B, C})
    found, stats = _svc(primary, fallback).series_with_stats([A, B, C, A], NOW, NOW)
    assert primary.calls == [[A, B, C]]  # deduplicated
    assert fallback.calls == [[B, C]]
    assert {c: s.source for c, s in found.items()} == {
        A: "open-meteo",
        B: "weatherapi",
        C: "weatherapi",
    }
    assert (stats.fetched, stats.failed) == (3, 0)
    assert stats.sources == {"open-meteo": 1, "weatherapi": 2}
    assert stats.errors == ("open-meteo: HTTP 503: busy",)


def test_fallback_failure_leaves_cells_unknown() -> None:
    primary = Fake("open-meteo", error="HTTP 429: Daily API request limit exceeded.")
    fallback = Fake("weatherapi", error="HTTP 403 (code 2007): quota")
    found, stats = _svc(primary, fallback).series_with_stats([A, B], NOW, NOW)
    assert found == {} and stats.failed == 2
    assert [p.cells_failed for p in stats.providers] == [2, 2]
    assert len(stats.errors) == 2


def test_quota_breaker_skips_provider_until_reset() -> None:
    clock = {"now": NOW}
    primary = Fake("open-meteo", exhausted_until=NOW + timedelta(hours=2))
    fallback = Fake("weatherapi", serves={A, B})
    svc = _svc(primary, fallback, now=lambda: clock["now"])
    svc.series_with_stats([A], NOW, NOW)
    _, stats = svc.series_with_stats([B], NOW, NOW)
    assert len(primary.calls) == 1  # not called again while its quota is spent
    assert stats.providers[0].skipped.startswith("paused until 2026-10-18T14:10")
    assert stats.sources == {"weatherapi": 1}


def test_cache_hit_avoids_any_provider_call() -> None:
    primary = Fake("open-meteo", serves={A, B})
    svc = _svc(primary)
    svc.series_with_stats([A, B], NOW, NOW + timedelta(hours=10))
    _, stats = svc.series_with_stats([A, B], NOW, NOW + timedelta(hours=48))
    assert len(primary.calls) == 1 and (stats.cached, stats.fetched) == (2, 0)


def test_stale_cache_entries_are_refetched() -> None:
    clock = {"now": NOW}
    primary = Fake("open-meteo", serves={A})
    svc = _svc(primary, now=lambda: clock["now"], ttl=3600)
    svc.series_with_stats([A], NOW, NOW)
    clock["now"] = NOW + timedelta(minutes=61)  # older than the TTL, even if still cached
    _, stats = svc.series_with_stats([A], NOW, NOW)
    assert len(primary.calls) == 2 and stats.fetched == 1


def test_short_horizon_provider_is_not_refetched_every_request() -> None:
    # WeatherAPI free returns ~3 days even when 9 were requested. The series records what was
    # asked for, so a repeat request for the same window is a cache hit (the extra hours are
    # known-unavailable), not another call.
    class ShortHorizon(Fake):
        def hourly(self, cells, start, end):
            out = super().hourly(cells, start, end)
            for s in out.values():
                s.gust_mph, s.wind_mph = s.gust_mph[:72], s.wind_mph[:72]
                s.rain_in_hr, s.snow_in_hr = s.rain_in_hr[:72], s.snow_in_hr[:72]
                s.requested_end = end
            return out

    provider = ShortHorizon("weatherapi", serves={A})
    svc = _svc(provider)
    found, _ = svc.series_with_stats([A], NOW, NOW + timedelta(days=9))
    svc.series_with_stats([A], NOW, NOW + timedelta(days=9))
    assert len(provider.calls) == 1
    assert found[A].at(NOW.replace(minute=0) + timedelta(days=5)) is None  # beyond horizon


def test_a_service_needs_a_provider() -> None:
    with pytest.raises(ValueError):
        WeatherService([], cache, grid_deg=0.25, ttl_s=60, model="t")


# --- Configuration ----------------------------------------------------------------------


@override_settings(
    WEATHER_PROVIDERS=["open-meteo", "weatherapi"], WEATHERAPI_KEY="", OPEN_METEO_API_KEY=""
)
def test_chain_skips_providers_without_a_key() -> None:
    from planner import deps

    chain = deps.weather_providers()
    assert [p.name for p in chain] == ["open-meteo"] and chain[0].endpoint == "free"


@override_settings(
    WEATHER_PROVIDERS=["open-meteo", "weatherapi"], WEATHERAPI_KEY="k", OPEN_METEO_API_KEY="paid"
)
def test_chain_with_both_keys() -> None:
    from planner import deps

    chain = deps.weather_providers()
    assert [p.name for p in chain] == ["open-meteo", "weatherapi"]
    assert chain[0].endpoint == "customer"


@override_settings(WEATHER_PROVIDERS=["darksky"])
def test_unknown_provider_is_a_configuration_error() -> None:
    from planner import deps

    with pytest.raises(ImproperlyConfigured):
        deps.weather_providers()


@override_settings(WEATHER_PROVIDERS=["weatherapi"], WEATHERAPI_KEY="")
def test_no_usable_provider_is_a_configuration_error() -> None:
    from planner import deps

    with pytest.raises(ImproperlyConfigured):
        deps.weather_providers()


# --- What the user is told ------------------------------------------------------------------


def test_notices_name_the_fallback_and_the_unavailable_cells() -> None:
    from planner.services.plan_trip import weather_notices
    from planner.services.weather import weather_sources

    primary = Fake("open-meteo", error="HTTP 429: Daily API request limit exceeded.")
    fallback = Fake("weatherapi", serves={B})
    svc = _svc(primary, fallback)
    found, stats = svc.series_with_stats([A, B], NOW, NOW)
    fallback_note, missing_note = weather_notices(stats, svc.provider_names)
    assert "fallback provider WeatherAPI.com (1 cells)" in fallback_note
    assert "Open-Meteo didn't return a complete forecast" in fallback_note
    assert missing_note.startswith("Weather was unavailable for 1 of 2 forecast grid cells")
    assert "open-meteo: HTTP 429: Daily API request limit exceeded." in missing_note
    assert weather_sources(found) == ["weatherapi"]


def test_no_notices_when_the_primary_served_everything() -> None:
    from planner.services.plan_trip import weather_notices

    svc = _svc(Fake("open-meteo", serves={A}), Fake("weatherapi", serves={A}))
    _, stats = svc.series_with_stats([A], NOW, NOW)
    assert weather_notices(stats, svc.provider_names) == []
