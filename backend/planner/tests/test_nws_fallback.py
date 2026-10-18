"""NWS fallback provider and field-level fallback: WeatherAPI.com first, NWS fills the gaps."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings

from planner.domain.models import LatLon, RiskLevel
from planner.presenters import plan_json
from planner.providers import nws as nws_module
from planner.providers.base import HourlySeries, WeatherFetch, merge_series
from planner.providers.nws import BASE_URL, NwsWeather, parse_gridpoint
from planner.providers.weatherapi import BASE_URL as WA_URL
from planner.providers.weatherapi import WeatherApiWeather
from planner.services.plan_trip import TripPlanner, TripRequest
from planner.services.weather import WeatherService
from planner.tests.conftest import FakeRouting, FakeWeather, calm

NOW = datetime(2026, 10, 18, 12, 10, tzinfo=UTC)
G0 = datetime(2026, 10, 18, 12, tzinfo=UTC)
UA = "test-app/1.0 (+https://example.test)"
DEN = LatLon(39.75, -105.0)
WYO = LatLon(41.25, -107.5)
KMH = 1.609344  # km/h per mph


def _clock():
    return NOW


def _layer(entries, uom):
    """entries: (hours after G0, duration in hours, value)."""
    return {
        "uom": uom,
        "values": [
            {"validTime": f"{(G0 + timedelta(hours=h)).isoformat()}/PT{d}H", "value": v}
            for h, d, v in entries
        ],
    }


def _grid(
    *,
    wind=((0, 12, 16.0934),),  # 10 mph for 12 h
    gust=((0, 12, 32.1869),),  # 20 mph
    qpf=((0, 6, 0), (6, 6, 0)),
    snow=((0, 6, 0), (6, 6, 0)),
    updated=NOW - timedelta(hours=3),
    center=DEN,
    speed_uom="wmoUnit:km_h-1",
) -> dict:
    d = 0.0125
    ring = [
        [center.lon - d, center.lat - d],
        [center.lon + d, center.lat - d],
        [center.lon + d, center.lat + d],
        [center.lon - d, center.lat + d],
        [center.lon - d, center.lat - d],
    ]
    return {
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "updateTime": updated.isoformat(),
            "windSpeed": _layer(wind, speed_uom),
            "windGust": _layer(gust, speed_uom),
            "quantitativePrecipitation": _layer(qpf, "wmoUnit:mm"),
            "snowfallAmount": _layer(snow, "wmoUnit:mm"),
            "probabilityOfPrecipitation": _layer(((0, 12, 100),), "wmoUnit:percent"),
        },
    }


def _hour(h: int) -> datetime:
    """The normalized hour ending h hours after G0."""
    return G0 + timedelta(hours=h)


# --- NWS normalization --------------------------------------------------------------------


def test_nws_units_and_held_wind_values() -> None:
    s, why = parse_gridpoint(_grid(), now=NOW)
    assert why == "" and s.start == _hour(1)
    w = s.at(_hour(5))
    assert w.wind_mph == pytest.approx(10.0, abs=1e-3)  # km/h -> mph
    assert w.gust_mph == pytest.approx(20.0, abs=1e-3)
    assert (w.rain_in_hr, w.snow_in_hr) == (0.0, 0.0)  # 6 h totals of exactly zero


def test_nws_hour_ending_takes_the_worse_neighbouring_value() -> None:
    gust = ((0, 3, 32.1869), (3, 9, 80.4672))  # 20 mph, then 50 mph from 15:00
    s, _ = parse_gridpoint(_grid(gust=gust), now=NOW)
    assert s.at(_hour(3)).gust_mph == pytest.approx(50, abs=1e-3)  # [14:00, 15:00) meets 15:00
    assert s.at(_hour(2)).gust_mph == pytest.approx(20, abs=1e-3)


def test_nws_multi_hour_precipitation_totals_are_never_spread_into_hourly_rates() -> None:
    qpf = ((0, 6, 0), (6, 6, 12.7))  # dry, then 0.5 in over 6 h: hourly rate unknowable
    snow = ((0, 1, 25.4), (1, 5, 0), (6, 6, 0))  # a genuine 1 h total of 1 in, then dry
    s, _ = parse_gridpoint(_grid(qpf=qpf, snow=snow), now=NOW)
    assert s.values_at(_hour(1))[3] == pytest.approx(1.0)  # snow mm -> in, hour [12, 13)
    assert s.values_at(_hour(6))[2] == 0.0  # hour [17, 18) is inside the dry 6 h period
    assert s.values_at(_hour(7))[2] is None  # [18, 19) is inside the wet one: unknown
    assert s.at(_hour(7)) is None  # so the hour is unknown, never zero


def test_nws_probability_of_precipitation_is_never_used_as_intensity() -> None:
    data = _grid()
    del data["properties"]["quantitativePrecipitation"]  # only PoP (100 %) is left
    s, _ = parse_gridpoint(data, now=NOW)
    assert all(v is None for v in s.rain_in_hr) and s.at(_hour(3)) is None


def test_nws_off_hour_times_and_unknown_units_are_ignored() -> None:
    data = _grid()
    data["properties"]["windGust"]["values"][0]["validTime"] = (
        f"{(G0 + timedelta(minutes=30)).isoformat()}/PT12H"
    )
    s, _ = parse_gridpoint(data, now=NOW)
    assert all(v is None for v in s.gust_mph)
    s2, _ = parse_gridpoint(_grid(speed_uom="wmoUnit:furlong_fortnight-1"), now=NOW)
    assert s2 is None  # no usable wind at all
    data3 = _grid()
    data3["properties"]["snowfallAmount"]["values"][0]["validTime"] = f"{G0.isoformat()}/PT30M"
    s3, _ = parse_gridpoint(data3, now=NOW)
    assert s3.values_at(_hour(1))[3] is None


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (None, "malformed response"),
        ({"properties": "x"}, "malformed response"),
        ({"properties": {}}, "no updateTime"),
        (_grid(updated=NOW - timedelta(hours=30)), "stale forecast"),
        ({"properties": {"updateTime": NOW.isoformat()}}, "no wind data"),
    ],
)
def test_nws_rejects_malformed_or_stale_forecasts(data, reason) -> None:
    s, why = parse_gridpoint(data, now=NOW)
    assert s is None and why.startswith(reason)


# --- NWS client ---------------------------------------------------------------------------


def _nws(**kw) -> NwsWeather:
    return NwsWeather(httpx.Client(), cache, user_agent=UA, backoff_s=0, now=_clock, **kw)


def _mock_points(router, cell: LatLon, grid_path: str, *, grid=None, status=200):
    lat = f"{cell.lat:.4f}".rstrip("0").rstrip(".")
    lon = f"{cell.lon:.4f}".rstrip("0").rstrip(".")
    points = router.get(f"{BASE_URL}/points/{lat},{lon}").mock(
        return_value=httpx.Response(
            status,
            json={"properties": {"forecastGridData": f"{BASE_URL}/gridpoints/{grid_path}"}},
        )
    )
    grid_route = router.get(f"{BASE_URL}/gridpoints/{grid_path}").mock(
        return_value=httpx.Response(200, json=grid or _grid(center=cell))
    )
    return points, grid_route


def test_nws_discovers_the_grid_and_identifies_itself() -> None:
    with respx.mock(assert_all_called=True) as router:
        points, grid = _mock_points(router, DEN, "BOU/63,62")
        out = _nws().hourly([DEN], G0, G0 + timedelta(hours=12))
    assert set(out) == {DEN} and out[DEN].source == "nws"
    for route in (points, grid):
        headers = route.calls[0].request.headers
        assert headers["User-Agent"] == UA and headers["Accept"] == "application/geo+json"
    assert out.calls.statuses == {"200": 2}


def test_nws_caches_point_metadata_and_forecasts() -> None:
    with respx.mock() as router:
        points, grid = _mock_points(router, DEN, "BOU/63,62")
        _nws().hourly([DEN], G0, G0)
        out = _nws().hourly([DEN], G0, G0)
    assert points.call_count == 1 and grid.call_count == 1
    assert set(out) == {DEN} and out.calls.requests == 0


def test_nws_is_only_asked_about_us_locations() -> None:
    with respx.mock() as router:  # any request would fail: no routes registered
        out = _nws().hourly([LatLon(51.5, -0.25), LatLon(-33.75, 151.25)], G0, G0)
        assert router.calls.call_count == 0
    assert dict(out) == {} and out.errors == ["2 cells outside NWS coverage (US only)"]


def test_nws_invalid_point_is_remembered() -> None:
    toronto = LatLon(43.75, -79.5)  # inside the CONUS box, outside NWS grids
    body = {"type": "https://api.weather.gov/problems/InvalidPoint", "status": 404}
    with respx.mock() as router:
        route = router.get(f"{BASE_URL}/points/43.75,-79.5").mock(
            return_value=httpx.Response(404, json=body)
        )
        first = _nws().hourly([toronto], G0, G0)
        _nws().hourly([toronto], G0, G0)
    assert route.call_count == 1 and dict(first) == {}
    assert first.errors == ["1 cells have no NWS forecast (outside its grids)"]


def test_nws_rate_limit_is_retried_boundedly_then_paused() -> None:
    with respx.mock() as router:
        route = router.get(url__startswith=f"{BASE_URL}/points/").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "0"}, json={"title": "Busy"})
        )
        out = _nws(max_workers=1, retries=2).hourly([DEN, WYO], G0, G0)
    assert route.call_count == 3  # 1 + 2 retries for the first point, then it stops asking
    assert out.quota_exhausted_until == NOW + timedelta(minutes=1)
    assert out.errors == ["points: HTTP 429: Busy"]


def test_nws_timeouts_and_server_errors_are_bounded() -> None:
    with respx.mock() as router:
        router.get(url__startswith=f"{BASE_URL}/points/").mock(
            side_effect=[httpx.ReadTimeout("slow"), httpx.Response(503), httpx.ReadTimeout("slow")]
        )
        out = _nws(retries=2).hourly([DEN], G0, G0)
    assert dict(out) == {} and out.calls.statuses == {"timeout": 2, "503": 1}
    assert out.quota_exhausted_until is None


def test_nws_never_follows_a_grid_url_to_another_host() -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/points/39.75,-105").mock(
            return_value=httpx.Response(
                200, json={"properties": {"forecastGridData": "https://evil.example/gridpoints/X"}}
            )
        )
        out = _nws().hourly([DEN], G0, G0)
        assert router.calls.call_count == 1
    assert dict(out) == {} and "no usable forecastGridData" in out.errors[0]


def test_nws_gridpoint_for_another_place_is_rejected() -> None:
    with respx.mock() as router:
        _mock_points(router, DEN, "BOU/63,62", grid=_grid(center=WYO))
        out = _nws().hourly([DEN], G0, G0)
    assert dict(out) == {} and out.errors == ["gridpoint does not match the requested location"]


def test_nws_needs_a_user_agent() -> None:
    with pytest.raises(ValueError):
        NwsWeather(httpx.Client(), cache, user_agent=" ")


def test_nws_coordinates_are_sent_with_at_most_four_decimals() -> None:
    assert nws_module._coords(LatLon(39.123456, -105.0)) == "39.1235,-105"


# --- Field-level fallback -----------------------------------------------------------------


def _series(source, *, hours=24, start=G0, wind=8.0, gust=15.0, rain=0.0, snow=0.0, **gaps):
    """A provider series; `gaps` maps a field to the hour indexes that are missing."""
    cols = {
        "wind_mph": [wind] * hours,
        "gust_mph": [gust] * hours,
        "rain_in_hr": [rain] * hours,
        "snow_in_hr": [snow] * hours,
    }
    for f, idxs in gaps.items():
        for i in idxs:
            cols[f][i] = None
    return HourlySeries(start=start, **cols, source=source, fetched_at=NOW)


class Canned:
    def __init__(self, name, by_cell, *, error=None, exhausted_until=None):
        self.name, self.by_cell, self.error = name, by_cell, error
        self.exhausted_until = exhausted_until
        self.calls: list[list[LatLon]] = []

    def hourly(self, cells, start, end):
        self.calls.append(list(cells))
        out = WeatherFetch()
        for c in cells:
            out.calls.record("200" if c in self.by_cell else "500")
            if c in self.by_cell:
                out[c] = self.by_cell[c]
        if self.error:
            out.errors.append(self.error)
        out.quota_exhausted_until = self.exhausted_until
        return out


def _svc(*providers, now=_clock) -> WeatherService:
    return WeatherService(list(providers), cache, grid_deg=0.25, ttl_s=3600, model="t", now=now)


def test_complete_primary_data_never_calls_the_fallback() -> None:
    nws = Canned("nws", {DEN: _series("nws")})
    found, stats = _svc(Canned("weatherapi", {DEN: _series("weatherapi")}), nws).series_with_stats(
        [DEN], _hour(1), _hour(10)
    )
    assert nws.calls == [] and found[DEN].providers == ["weatherapi"]
    assert stats.sources == {"weatherapi": 1}


def test_missing_field_is_filled_from_the_fallback_and_attributed() -> None:
    primary = Canned("weatherapi", {DEN: _series("weatherapi", gust=15.0, gust_mph=[4])})
    nws = Canned("nws", {DEN: _series("nws", gust=31.0)})
    found, stats = _svc(primary, nws).series_with_stats([DEN], _hour(1), _hour(10))
    s = found[DEN]
    assert s.at(G0 + timedelta(hours=4)).gust_mph == 31.0  # filled for that hour only
    assert s.at(G0 + timedelta(hours=5)).gust_mph == 15.0  # primary values are never replaced
    assert s.sources_at(G0 + timedelta(hours=4)) == {
        "wind_mph": "weatherapi",
        "gust_mph": "nws",
        "rain_in_hr": "weatherapi",
        "snow_in_hr": "weatherapi",
    }
    assert s.sources_at(G0 + timedelta(hours=5))["gust_mph"] == "weatherapi"
    assert stats.sources == {"weatherapi": 1, "nws": 1} and stats.incomplete == 0


def test_fill_needs_the_same_forecast_hour() -> None:
    # The fallback has no value for the primary's gap hour (its data starts 6 h later), so
    # the gap stays unknown rather than borrowing a neighbouring hour.
    primary = Canned("weatherapi", {DEN: _series("weatherapi", rain_in_hr=[2])})
    nws = Canned("nws", {DEN: _series("nws", start=G0 + timedelta(hours=6), rain=0.9)})
    found, stats = _svc(primary, nws).series_with_stats([DEN], _hour(1), _hour(10))
    assert found[DEN].values_at(G0 + timedelta(hours=2))[2] is None
    assert found[DEN].at(G0 + timedelta(hours=2)) is None  # unknown, never zero
    assert stats.incomplete == 1


def test_merge_ignores_invalid_fallback_values() -> None:
    base = _series("weatherapi", snow_in_hr=[3])
    bad = _series("nws", snow=float("nan"))
    merged, filled = merge_series(base, bad)
    assert filled == 0 and merged.values_at(G0 + timedelta(hours=3))[3] is None


def test_fallback_can_extend_past_the_primary_horizon() -> None:
    primary = Canned("weatherapi", {DEN: _series("weatherapi", hours=6)})
    nws = Canned("nws", {DEN: _series("nws", hours=24, gust=22.0)})
    found, _ = _svc(primary, nws).series_with_stats([DEN], _hour(1), _hour(12))
    s = found[DEN]
    assert s.at(G0 + timedelta(hours=3)).gust_mph == 15.0  # primary
    assert s.at(G0 + timedelta(hours=10)).gust_mph == 22.0  # fallback beyond 6 h
    assert s.sources_at(G0 + timedelta(hours=10))["wind_mph"] == "nws"


def test_gaps_left_after_the_whole_chain_are_cached_not_refetched() -> None:
    primary = Canned("weatherapi", {DEN: _series("weatherapi", rain_in_hr=[2])})
    nws = Canned("nws", {DEN: _series("nws", rain_in_hr=[2])})
    svc = _svc(primary, nws)
    svc.series_with_stats([DEN], _hour(1), _hour(10))
    _, stats = svc.series_with_stats([DEN], _hour(1), _hour(10))
    assert len(primary.calls) == len(nws.calls) == 1 and stats.cached == 1
    # A wider window was never checked against the chain, so it is asked again.
    svc.series_with_stats([DEN], _hour(1), _hour(20))
    assert len(primary.calls) == 2


def test_primary_failure_falls_back_for_the_whole_cell() -> None:
    primary = Canned("weatherapi", {}, error="HTTP 403 (code 2007): quota")
    nws = Canned("nws", {DEN: _series("nws")})
    found, stats = _svc(primary, nws).series_with_stats([DEN, WYO], _hour(1), _hour(4))
    assert set(found) == {DEN} and found[DEN].source == "nws"
    assert nws.calls == [[DEN, WYO]] and stats.failed == 1


@respx.mock
def test_weatherapi_quota_then_nws_end_to_end() -> None:
    respx.get(WA_URL).mock(
        return_value=httpx.Response(403, json={"error": {"code": 2007, "message": "quota"}})
    )
    _mock_points(respx, DEN, "BOU/63,62")
    wa = WeatherApiWeather(httpx.Client(), api_key="K", backoff_s=0, now=_clock)
    svc = _svc(wa, _nws())
    found, stats = svc.series_with_stats([DEN], _hour(1), _hour(10))
    assert found[DEN].source == "nws"
    assert [p.name for p in stats.providers] == ["weatherapi", "nws"]
    assert stats.providers[0].statuses == {"403": 1}
    # The quota breaker now skips WeatherAPI until next month.
    cache.delete(svc._key(DEN))
    _, again = svc.series_with_stats([DEN], _hour(1), _hour(10))
    assert again.providers[0].skipped == (
        "paused until 2026-11-01T00:00+00:00 (HTTP 403 (code 2007): quota)"
    )


@respx.mock
def test_weatherapi_for_another_location_is_not_used() -> None:
    body = {
        "location": {"lat": 45.0, "lon": -100.0},
        "forecast": {
            "forecastday": [
                {
                    "hour": [
                        {
                            "time_epoch": int((G0 + timedelta(hours=h)).timestamp()),
                            "wind_mph": 5,
                            "gust_mph": 9,
                            "precip_in": 0,
                            "snow_cm": 0,
                        }
                        for h in range(4)
                    ]
                }
            ]
        },
    }
    respx.get(WA_URL).mock(return_value=httpx.Response(200, json=body))
    out = WeatherApiWeather(httpx.Client(), api_key="K", now=_clock).hourly([DEN], G0, G0)
    assert dict(out) == {} and out.errors == ["WeatherAPI answered for a different location"]


# --- Trip pipeline ------------------------------------------------------------------------


class Named(FakeWeather):
    """FakeWeather that names itself and can leave one field out everywhere."""

    def __init__(self, name, fn, *, drop=None):
        super().__init__(fn)
        self.name, self.drop = name, drop

    def hourly(self, cells, start, end):
        out = WeatherFetch()
        for cell, s in super().hourly(cells, start, end).items():
            s.source = self.name
            if self.drop:
                setattr(s, self.drop, [None] * len(getattr(s, self.drop)))
            out[cell] = s
        return out


def _plan(tomtom_routes, departure, *providers):
    svc = WeatherService(list(providers), cache, grid_deg=0.25, ttl_s=600, model="t")
    planner = TripPlanner(FakeRouting(tomtom_routes), svc, tare_lb=0)
    return planner.plan(
        TripRequest(_place(39.7392, -104.9903), _place(40.7608, -111.891), departure, 36_000, 25)
    )


def _place(lat, lon):
    from planner.providers.base import Place

    return Place("x", lat, lon)


def test_plan_records_each_checkpoint_source_when_a_fallback_fills_gusts(
    tomtom_routes, departure
) -> None:
    plan = _plan(
        tomtom_routes,
        departure,
        Named("weatherapi", calm, drop="gust_mph"),
        Named("nws", calm),
    )
    assert plan.status.value == "recommended"
    cp = plan.routes[0].scored.checkpoints[1]
    assert cp.weather_source == {
        "wind_mph": "weatherapi",
        "gust_mph": "nws",
        "rain_in_hr": "weatherapi",
        "snow_in_hr": "weatherapi",
    }
    payload = plan_json(plan)["routes"][0]["checkpoints"][1]
    assert payload["weather_source"]["gust_mph"] == "nws"
    assert plan.meta["weather_sources"] == ["nws", "weatherapi"]
    assert any("fallback provider the National Weather Service" in n for n in plan.notices)


def test_a_field_no_provider_has_leaves_checkpoints_unknown_and_unrecommended(
    tomtom_routes, departure
) -> None:
    plan = _plan(
        tomtom_routes,
        departure,
        Named("weatherapi", calm, drop="rain_in_hr"),
        Named("nws", calm, drop="rain_in_hr"),
    )
    assert plan.status.value == "none" and plan.none_reason == "no_forecast"
    cps = [cp for r in plan.routes for cp in r.scored.checkpoints]
    assert all(cp.weather is None and cp.risk is None for cp in cps)
    assert all(cp.weather_source is None for cp in cps)
    assert any(
        "had an incomplete forecast for the hour the truck passes" in n for n in plan.notices
    )


def test_fallback_data_is_scored_with_the_same_rules(tomtom_routes, departure) -> None:
    def gale(cell, hour):
        return (20.0, 50.0, 0.0, 0.0)  # 50 mph gusts: No Travel above 30,000 lb

    plan = _plan(
        tomtom_routes, departure, Named("weatherapi", gale, drop="gust_mph"), Named("nws", gale)
    )
    levels = {cp.risk.level for r in plan.routes for cp in r.scored.checkpoints if cp.risk}
    assert levels == {RiskLevel.NO_TRAVEL} and plan.recommended_id is None


# --- Configuration ------------------------------------------------------------------------


@override_settings(WEATHER_PROVIDERS=["weatherapi", "nws"], WEATHERAPI_KEY="k", NWS_USER_AGENT="")
def test_default_chain_is_weatherapi_then_nws() -> None:
    from planner import deps

    chain = deps.weather_providers()
    assert [p.name for p in chain] == ["weatherapi", "nws"]
    assert chain[1]._headers["User-Agent"] == deps.USER_AGENT


@override_settings(WEATHER_PROVIDERS=["weatherapi", "nws"], WEATHERAPI_KEY="")
def test_without_a_weatherapi_key_only_nws_is_used() -> None:
    from planner import deps

    assert [p.name for p in deps.weather_providers()] == ["nws"]
