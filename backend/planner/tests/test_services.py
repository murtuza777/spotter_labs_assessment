from datetime import timedelta

import pytest
from django.core.cache import cache

from planner.domain.geo import resample
from planner.domain.models import LatLon, RiskLevel
from planner.providers.base import Place, ProviderError, RouteOption
from planner.services.heatmap import HEATMAP_HOURS, HeatmapBuilder
from planner.services.plan_trip import TripPlanner, TripRequest, _detour_points
from planner.services.weather import WeatherService
from planner.tests.conftest import FakeRouting, FakeWeather, calm

DEN = Place("Denver, CO", 39.7392, -104.9903)
SLC = Place("Salt Lake City, UT", 40.7608, -111.8910)


def _service(weather) -> WeatherService:
    return WeatherService(weather, cache, grid_deg=0.25, ttl_s=600, model="test")


def _request(departure, *, load=36_000, interval=25) -> TripRequest:
    return TripRequest(DEN, SLC, departure, load, interval)


def test_plan_three_routes_with_checkpoints_and_etas(tomtom_routes, departure) -> None:
    planner = TripPlanner(FakeRouting(tomtom_routes), _service(FakeWeather(calm)), tare_lb=35_000)
    plan = planner.plan(_request(departure, interval=25))

    assert [r.id for r in plan.routes] == ["A", "B", "C"]
    for route, option in zip(plan.routes, tomtom_routes, strict=True):
        cps = route.scored.checkpoints
        assert cps[0].mile == 0 and cps[0].eta == departure
        assert cps[-1].mile == pytest.approx(route.distance_mi)
        assert cps[-1].eta == departure + timedelta(seconds=option.duration_s)
        assert all(a.eta <= b.eta for a, b in zip(cps, cps[1:], strict=False))
        assert sum(cp.owned_miles for cp in cps) == pytest.approx(route.distance_mi)
        assert all(cp.risk and cp.risk.level == RiskLevel.LOW for cp in cps)
        assert sum(s.end_mile - s.start_mile for s in route.segments) == pytest.approx(
            route.distance_mi
        )
    # All calm: travel time decides, so the fastest TomTom route (A) wins.
    assert plan.recommended_id == "A"
    assert "travel time" in plan.reason or "h" in plan.reason


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_checkpoint_spacing_follows_interval(tomtom_routes, departure, interval) -> None:
    planner = TripPlanner(FakeRouting(tomtom_routes), _service(FakeWeather(calm)), tare_lb=0)
    route = planner.plan(_request(departure, interval=interval)).routes[0]
    miles = [cp.mile for cp in route.scored.checkpoints]
    assert miles[1] - miles[0] == pytest.approx(interval)
    assert len(miles) == int(route.distance_mi // interval) + 1 + (
        route.distance_mi % interval > 0.05
    )


def test_eta_based_sampling_picks_weather_at_arrival_hour(tomtom_routes, departure) -> None:
    storm_hour = departure + timedelta(hours=4)

    def storm_after_4h(cell, hour):
        return (10, 60, 0, 0) if hour >= storm_hour else (5, 10, 0, 0)

    planner = TripPlanner(
        FakeRouting(tomtom_routes), _service(FakeWeather(storm_after_4h)), tare_lb=0
    )
    route = planner.plan(_request(departure)).routes[0]
    for cp in route.scored.checkpoints:
        expected = RiskLevel.NO_TRAVEL if cp.forecast_hour >= storm_hour else RiskLevel.LOW
        assert cp.risk.level == expected


def test_storm_on_fastest_route_changes_recommendation(tomtom_routes, departure) -> None:
    # Route A (fastest) runs north through Wyoming; route C (slowest) stays south in Colorado.
    def wyoming_wind(cell, hour):
        return (20, 50, 0, 0) if cell.lat >= 41.0 else (5, 10, 0, 0)

    planner = TripPlanner(
        FakeRouting(tomtom_routes), _service(FakeWeather(wyoming_wind)), tare_lb=0
    )
    plan = planner.plan(_request(departure, load=36_000))
    by_id = {r.id: r for r in plan.routes}
    # 50 mph gusts with a 36,000 lb load is No Travel.
    assert by_id["A"].scored.summary.no_travel_miles > 0
    best = by_id[plan.recommended_id]
    assert best.scored.summary.no_travel_miles == min(
        r.scored.summary.no_travel_miles for r in plan.routes
    )
    assert plan.recommended_id != "A"
    assert by_id["A"].rank == 3


def test_unknown_weather_is_reported_not_scored(tomtom_routes, departure) -> None:
    weather = FakeWeather(calm)
    service = _service(weather)
    weather.fail_cells = {service.cell_for(LatLon(39.75, -105.0))}
    plan = TripPlanner(FakeRouting(tomtom_routes), service, tare_lb=0).plan(_request(departure))
    assert plan.routes[0].scored.summary.unknown_miles > 0
    # Every route starts in the failed cell, so none has a complete forecast: provisional pick.
    assert plan.status.value == "provisional"
    assert any("provisional pick" in w for w in plan.warnings)
    assert all(r.eligibility == "incomplete_forecast" for r in plan.routes)


def test_weather_cells_are_snapped_deduped_and_cached(tomtom_routes, departure) -> None:
    weather = FakeWeather(calm)
    planner = TripPlanner(FakeRouting(tomtom_routes), _service(weather), tare_lb=0)
    planner.plan(_request(departure, interval=10))
    first_batch = list(weather.requested)
    assert len(first_batch) == len(set(first_batch))
    assert all((c.lat / 0.25).is_integer() and (c.lon / 0.25).is_integer() for c in first_batch)

    planner.plan(_request(departure, interval=10))
    assert weather.requested == first_batch  # second plan served from cache


def test_routing_weight_includes_tare(tomtom_routes, departure) -> None:
    routing = FakeRouting(tomtom_routes)
    TripPlanner(routing, _service(FakeWeather(calm)), tare_lb=35_000).plan(
        _request(departure, load=45_000)
    )
    assert routing.calls[0]["weight"] == round(80_000 * 0.45359237)
    assert routing.calls[0]["max_alternatives"] == 2


def _shifted(option: RouteOption, dlat: float) -> RouteOption:
    pts = option.points
    n = len(pts)
    bent = [LatLon(p.lat + dlat * (1 - abs(2 * i / (n - 1) - 1)), p.lon) for i, p in enumerate(pts)]
    return RouteOption(bent, option.length_m * 1.1, option.duration_s * 1.2, [])


def test_detour_fallback_fills_to_three_routes(tomtom_routes, departure) -> None:
    main = tomtom_routes[:1]
    routing = FakeRouting(main, detours=[_shifted(main[0], 1.5), _shifted(main[0], -1.5)])
    plan = TripPlanner(routing, _service(FakeWeather(calm)), tare_lb=0).plan(_request(departure))
    assert [r.source for r in plan.routes] == ["routing_api", "detour", "detour"]
    assert any(
        "Route B and C are detours: TomTom truck routing through a waypoint" in n
        for n in plan.notices
    )
    assert plan.routes[0].waypoint is None
    assert all(r.waypoint is not None for r in plan.routes[1:])
    assert plan.meta["routing_lookups"] == 3  # 1 alternatives request + 2 detours, no more
    assert sum(1 for c in routing.calls if c["via"] is not None) == 2


def test_duplicate_alternatives_are_dropped(tomtom_routes, departure) -> None:
    routing = FakeRouting([tomtom_routes[0], tomtom_routes[0]])
    plan = TripPlanner(routing, _service(FakeWeather(calm)), tare_lb=0).plan(_request(departure))
    assert len(plan.routes) == 1
    assert any("Only 1 meaningful" in n and "(1 more was the same road)" in n for n in plan.notices)


def test_no_routes_raises(departure) -> None:
    with pytest.raises(ProviderError) as err:
        TripPlanner(FakeRouting([]), _service(FakeWeather(calm)), tare_lb=0).plan(
            _request(departure)
        )
    assert err.value.code == "no_route"


def test_detour_points_are_perpendicular_and_offset() -> None:
    line = [LatLon(40.0, -110.0), LatLon(40.0, -100.0)]
    a, b = _detour_points(line)
    assert a.lon == pytest.approx(-105.0, abs=0.01) and b.lon == pytest.approx(-105.0, abs=0.01)
    assert a.lat > 40.5 and b.lat < 39.5


def test_heatmap_frames_shape_and_values(tomtom_routes, departure) -> None:
    def windy(cell, hour):
        return (30, 40, 0.3, 0.0)

    builder = HeatmapBuilder(_service(FakeWeather(windy)), max_points=150)
    routes = [resample(r.points, 20) for r in tomtom_routes]
    heat = builder.build(routes, departure, load_lb=45_000)
    assert len(heat.hours) == HEATMAP_HOURS + 1
    assert heat.hours[0] == departure
    assert 0 < len(heat.points) <= 150
    for metric in ("risk", "gust", "rain", "snow"):
        assert len(heat.frames[metric]) == HEATMAP_HOURS + 1
        assert all(len(row) == len(heat.points) for row in heat.frames[metric])
    # 40 mph gust (High) with a 45,000 lb load is Severe.
    assert heat.frames["risk"][0][0] == int(RiskLevel.SEVERE)
    assert heat.frames["gust"][0][0] == 40


def test_two_api_alternatives_need_one_detour(tomtom_routes, departure) -> None:
    routing = FakeRouting(tomtom_routes[:2], detours=[_shifted(tomtom_routes[0], 1.5)] * 2)
    plan = TripPlanner(routing, _service(FakeWeather(calm)), tare_lb=0).plan(_request(departure))
    assert [r.source for r in plan.routes] == ["routing_api", "routing_api", "detour"]
    assert any("TomTom returned 2 distinct truck route(s). Route C is" in n for n in plan.notices)


def test_three_api_alternatives_make_no_extra_calls(tomtom_routes, departure) -> None:
    routing = FakeRouting(tomtom_routes)
    plan = TripPlanner(routing, _service(FakeWeather(calm)), tare_lb=0).plan(_request(departure))
    assert plan.meta["routing_lookups"] == 1 and plan.notices == []


def test_failed_detours_show_fewer_routes_honestly(tomtom_routes, departure) -> None:
    routing = FakeRouting(tomtom_routes[:1], detours=[])  # detour calls return nothing
    plan = TripPlanner(routing, _service(FakeWeather(calm)), tare_lb=0).plan(_request(departure))
    assert len(plan.routes) == 1
    [notice] = plan.notices
    assert notice.startswith("Only 1 meaningful route(s) could be found. TomTom returned 1")
    assert "TomTom found no truck route through a waypoint" in notice


def test_checkpoints_outside_forecast_coverage_are_unknown(tomtom_routes, departure) -> None:
    class ShortForecast(FakeWeather):
        def hourly(self, cells, start, end):
            return super().hourly(cells, start, start + timedelta(hours=3))  # only 4 hours

    service = _service(ShortForecast(calm))
    plan = TripPlanner(FakeRouting(tomtom_routes), service, tare_lb=0).plan(_request(departure))
    cps = plan.routes[0].scored.checkpoints
    late = [cp for cp in cps if cp.forecast_hour > departure + timedelta(hours=3)]
    assert late and all(cp.weather is None and cp.risk is None for cp in late)
    assert plan.routes[0].scored.summary.unknown_miles > 0


def test_heatmap_reports_unknown_cells_and_stats(tomtom_routes, departure) -> None:
    weather = FakeWeather(calm)
    service = _service(weather)
    routes = [resample(r.points, 20) for r in tomtom_routes]
    first = HeatmapBuilder(service, max_points=60).build(routes, departure, load_lb=0)
    assert first.meta["weather"]["fetched"] > 0 and first.meta["unknown_cells"] == 0
    weather.fail_cells = set()
    again = HeatmapBuilder(service, max_points=60).build(routes, departure, load_lb=0)
    assert again.meta["weather"]["fetched"] == 0  # all from cache


def _scaled(option: RouteOption, *, dlat: float, length: float, duration: float) -> RouteOption:
    bent = _shifted(option, dlat)
    return RouteOption(bent.points, option.length_m * length, option.duration_s * duration, [])


@pytest.mark.parametrize(
    ("length", "duration", "why"),
    [
        (1.6, 1.2, "1.60x the fastest route's distance"),
        (1.2, 1.9, "1.90x the fastest route's drive time"),
    ],
)
def test_unreasonable_detours_are_rejected(tomtom_routes, departure, length, duration, why) -> None:
    main = tomtom_routes[0]
    detours = [_scaled(main, dlat=1.5, length=length, duration=duration)] * 2
    plan = TripPlanner(
        FakeRouting([main], detours=detours), _service(FakeWeather(calm)), tare_lb=0
    ).plan(_request(departure))
    assert [r.source for r in plan.routes] == ["routing_api"]
    assert why in plan.notices[-1]


def test_detour_that_repeats_the_main_route_is_rejected(tomtom_routes, departure) -> None:
    main = tomtom_routes[0]
    near_copy = RouteOption(main.points, main.length_m * 1.01, main.duration_s * 1.01, [])
    plan = TripPlanner(
        FakeRouting([main], detours=[near_copy, near_copy]), _service(FakeWeather(calm)), tare_lb=0
    ).plan(_request(departure))
    assert len(plan.routes) == 1
    assert "mostly repeat an existing route" in plan.notices[-1]


def test_out_and_back_spur_is_detected() -> None:
    from planner.services.plan_trip import _doubles_back

    # East 50 mi, then 20 mi north to the waypoint and straight back, then east again.
    east = [LatLon(40.0, -105.0 + i * 0.02) for i in range(60)]
    spur_up = [LatLon(40.0 + i * 0.01, east[-1].lon) for i in range(1, 30)]
    spur_down = list(reversed(spur_up))[1:] + [east[-1]]
    on = [LatLon(40.0, east[-1].lon + i * 0.02) for i in range(1, 60)]
    route = east + spur_up + spur_down + on
    assert _doubles_back(route, spur_up[-1])
    through = east + on
    assert not _doubles_back(through, east[-1])


def test_route_similarity_is_geometric(tomtom_routes) -> None:
    from planner.domain.geo import route_similarity

    a, b, c = (r.points for r in tomtom_routes)
    assert route_similarity(a, a) == pytest.approx(1.0)
    assert route_similarity(a, list(reversed(a))) == pytest.approx(1.0)
    assert route_similarity(a, b) < 0.5  # Denver->SLC via I-80 vs via I-70
    # The same road with extra vertices (densified) is still the same road.
    dense = [
        q
        for p1, p2 in zip(a, a[1:], strict=False)
        for q in (p1, LatLon((p1.lat + p2.lat) / 2, (p1.lon + p2.lon) / 2))
    ]
    assert route_similarity(a, dense + [a[-1]]) > 0.97


def test_checkpoints_report_the_queried_cell_and_risk_factors(tomtom_routes, departure) -> None:
    plan = TripPlanner(FakeRouting(tomtom_routes), _service(FakeWeather(calm)), tare_lb=0).plan(
        _request(departure)
    )
    cp = plan.routes[0].scored.checkpoints[3]
    assert cp.weather_cell == LatLon(round(cp.point.lat * 4) / 4, round(cp.point.lon * 4) / 4)
    names = [f.name for f in cp.risk.factors]
    assert names == ["wind", "rain", "snow"]
    assert cp.risk.level == max(f.level for f in cp.risk.factors)
