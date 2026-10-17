from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.test import Client

from planner import deps
from planner.domain.geo import encode_polyline
from planner.providers.base import Place, ProviderError
from planner.services.heatmap import HeatmapBuilder
from planner.services.plan_trip import TripPlanner
from planner.services.weather import WeatherService
from planner.tests.conftest import FakeRouting, FakeWeather, calm


@pytest.fixture
def api(monkeypatch, tomtom_routes):
    service = WeatherService(FakeWeather(calm), cache, grid_deg=0.25, ttl_s=60, model="t")
    monkeypatch.setattr(
        deps, "trip_planner", lambda: TripPlanner(FakeRouting(tomtom_routes), service, tare_lb=0)
    )
    monkeypatch.setattr(deps, "heatmap_builder", lambda: HeatmapBuilder(service, max_points=50))
    return Client()


def _body(**overrides) -> dict:
    body = {
        "origin": {"label": "Denver, CO", "lat": 39.7392, "lon": -104.9903},
        "destination": {"label": "Salt Lake City, UT", "lat": 40.7608, "lon": -111.891},
        "departure_time": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
        "load_weight_lb": 36000,
        "sample_interval_mi": 25,
    }
    body.update(overrides)
    return body


def test_plan_success_shape(api) -> None:
    res = api.post("/api/plan/", _body(), content_type="application/json")
    assert res.status_code == 200, res.content
    data = res.json()
    assert data["recommended_route_id"] in {"A", "B", "C"}
    assert len(data["routes"]) == 3
    route = data["routes"][0]
    assert set(route) >= {
        "id",
        "rank",
        "distance_mi",
        "duration_s",
        "geometry",
        "summary",
        "segments",
        "checkpoints",
    }
    assert set(route["summary"]["miles_by_level"]) == {
        "low",
        "moderate",
        "high",
        "severe",
        "no_travel",
    }
    cp = route["checkpoints"][1]
    assert cp["mile"] == 25.0
    assert cp["eta"].endswith("Z")
    assert cp["risk"]["level"] == "low"
    assert cp["weather"]["gust_mph"] == 12.0


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"sample_interval_mi": 15}, "sample_interval_mi"),
        ({"load_weight_lb": 90_000}, "load_weight_lb"),
        ({"load_weight_lb": -1}, "load_weight_lb"),
        (
            {"departure_time": (datetime.now(UTC) - timedelta(hours=3)).isoformat()},
            "departure_time",
        ),
        ({"departure_time": (datetime.now(UTC) + timedelta(days=9)).isoformat()}, "departure_time"),
        ({"destination": {"label": "Denver", "lat": 39.7393, "lon": -104.9904}}, "destination"),
        ({"origin": {"label": "x", "lat": 120, "lon": 0}}, "origin"),
    ],
)
def test_plan_validation_errors(api, overrides, field) -> None:
    res = api.post("/api/plan/", _body(**overrides), content_type="application/json")
    assert res.status_code == 400
    err = res.json()["error"]
    assert err["code"] == "invalid_request"
    assert field in err["details"]


def test_plan_provider_error_shape(monkeypatch) -> None:
    class Broken:
        def plan(self, req):
            raise ProviderError("routing_unavailable", "down", status=502)

    monkeypatch.setattr(deps, "trip_planner", lambda: Broken())
    res = Client().post("/api/plan/", _body(), content_type="application/json")
    assert res.status_code == 502
    assert res.json() == {"error": {"code": "routing_unavailable", "message": "down"}}


def test_heatmap_endpoint(api, tomtom_routes) -> None:
    body = {
        "routes": [encode_polyline(r.points[::20]) for r in tomtom_routes],
        "departure_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "load_weight_lb": 20000,
    }
    res = api.post("/api/heatmap/", body, content_type="application/json")
    assert res.status_code == 200, res.content
    data = res.json()
    assert len(data["hours"]) == 49
    assert len(data["frames"]["risk"]) == 49
    assert len(data["frames"]["risk"][0]) == len(data["points"]) <= 50


def test_heatmap_rejects_bad_polyline(api) -> None:
    body = {"routes": ["?"], "departure_time": datetime.now(UTC).isoformat(), "load_weight_lb": 1}
    assert api.post("/api/heatmap/", body, content_type="application/json").status_code == 400


def test_geocode_caches_results(monkeypatch) -> None:
    calls = []

    class Geo:
        def search(self, q, limit=6):
            calls.append(q)
            return [Place("Denver, Colorado, US", 39.74, -104.99)]

    monkeypatch.setattr(deps, "geocoder", lambda: Geo())
    client = Client()
    for _ in range(2):
        res = client.get("/api/geocode/", {"q": "Denver"})
        assert res.status_code == 200
        assert res.json()["results"][0]["label"] == "Denver, Colorado, US"
    assert calls == ["Denver"]
    assert client.get("/api/geocode/", {"q": "D"}).status_code == 400
