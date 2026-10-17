from datetime import UTC, datetime, timedelta

from django.core.cache import cache

from planner.domain.models import LatLon
from planner.providers.base import Place
from planner.services.plan_trip import TripPlanner, TripRequest
from planner.services.routing import CachedRouting
from planner.services.weather import WeatherService
from planner.tests.conftest import FakeRouting, FakeWeather, calm

DEN, SLC = LatLon(39.7392, -104.9903), LatLon(40.7608, -111.891)
DEPART = datetime(2026, 10, 18, 14, tzinfo=UTC)


def _call(routing, **overrides):
    args = {"depart_at": DEPART, "vehicle_weight_kg": 30_000, "max_alternatives": 2, "via": None}
    args.update(overrides)
    return routing.routes(DEN, SLC, **args)


def test_identical_requests_hit_the_cache(tomtom_routes) -> None:
    inner = FakeRouting(tomtom_routes)
    routing = CachedRouting(inner, cache, ttl_s=60)
    assert len(_call(routing)) == 3
    assert len(_call(routing)) == 3
    assert len(inner.calls) == 1 and routing.hits == 1


def test_any_input_change_is_a_new_request(tomtom_routes) -> None:
    inner = FakeRouting(tomtom_routes)
    routing = CachedRouting(inner, cache, ttl_s=60)
    _call(routing)
    _call(routing, depart_at=DEPART + timedelta(hours=1))
    _call(routing, vehicle_weight_kg=31_000)
    _call(routing, max_alternatives=0)
    _call(routing, via=LatLon(41, -106))
    assert len(inner.calls) == 5 and routing.hits == 0


def test_empty_answers_are_not_cached() -> None:
    inner = FakeRouting([])
    routing = CachedRouting(inner, cache, ttl_s=60)
    assert _call(routing) == [] and _call(routing) == []
    assert len(inner.calls) == 2


def test_resubmitting_a_plan_makes_no_routing_or_weather_calls(tomtom_routes) -> None:
    inner, weather = FakeRouting(tomtom_routes), FakeWeather(calm)
    service = WeatherService(weather, cache, grid_deg=0.25, ttl_s=600, model="t")
    planner = TripPlanner(CachedRouting(inner, cache, ttl_s=60), service, tare_lb=0)
    req = TripRequest(Place("a", DEN.lat, DEN.lon), Place("b", SLC.lat, SLC.lon), DEPART, 1000, 25)
    first = planner.plan(req)
    requested = len(weather.requested)
    second = planner.plan(req)
    assert len(inner.calls) == 1
    assert len(weather.requested) == requested
    assert second.meta["weather"]["fetched"] == 0
    assert second.recommended_id == first.recommended_id
