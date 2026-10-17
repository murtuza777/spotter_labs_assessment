"""Export deterministic API responses for the frontend's Playwright tests.

The responses come from the real TripPlanner, HeatmapBuilder and presenters, fed the recorded
TomTom routes (planner/tests/fixtures) and synthetic weather. So the e2e fixtures always
match the real API contract, and regenerating them after a backend change keeps both sides
honest:

    uv run python scripts/export_e2e_fixtures.py
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.core.cache import cache  # noqa: E402

from planner.domain.geo import decode_polyline  # noqa: E402
from planner.domain.models import LatLon  # noqa: E402
from planner.presenters import heatmap_json, plan_json  # noqa: E402
from planner.providers.base import Place, RouteOption  # noqa: E402
from planner.providers.tomtom import parse_route  # noqa: E402
from planner.services.heatmap import HeatmapBuilder  # noqa: E402
from planner.services.plan_trip import TripPlanner, TripRequest  # noqa: E402
from planner.services.weather import WeatherService  # noqa: E402
from planner.tests.conftest import FakeRouting, FakeWeather, load_fixture  # noqa: E402

OUT = BACKEND.parent / "frontend" / "e2e" / "fixtures"
DEPARTURE = datetime(2026, 10, 18, 14, tzinfo=UTC)
DEN = Place("Denver, Colorado, US", 39.7392, -104.9903)
SLC = Place("Salt Lake City, Utah, US", 40.7608, -111.891)


def wyoming_wind(cell, hour):
    """50 mph gusts north of 41°N (I-80 through Wyoming): No Travel above 30,000 lb."""
    return (20.0, 50.0, 0.0, 0.0) if cell.lat >= 41.0 else (6.0, 12.0, 0.02, 0.0)


def gale_everywhere(cell, hour):
    return (40.0, 60.0, 0.0, 0.0)


def calm(cell, hour):
    return (6.0, 12.0, 0.0, 0.0)


def bent(option, dlat: float, *, length: float = 1.15, duration: float = 1.25):
    """A test-only detour shape: the route bowed north/south in the middle. Used only in these
    mock fixtures (as if TomTom had routed through a waypoint), never in the app."""
    pts = option.points
    n = len(pts)
    points = [
        LatLon(p.lat + dlat * (1 - abs(2 * i / (n - 1) - 1)), p.lon) for i, p in enumerate(pts)
    ]
    return RouteOption(points, option.length_m * length, option.duration_s * duration, [])


# Failing region around Denver: covers the origin checkpoints and some heatmap grid points.
DENVER_REGION = {LatLon(lat / 4, lon / 4) for lat in range(156, 163) for lon in range(-424, -415)}

# name -> (weather fn, failing cells, routes TomTom "returns", detours TomTom "returns")
SCENARIOS = {
    "mixed": (wyoming_wind, set(), 3, 0),
    "no_safe_route": (gale_everywhere, set(), 3, 0),
    "partial_forecast": (calm, DENVER_REGION, 3, 0),
    "detour": (calm, set(), 2, 2),
    "two_routes": (calm, set(), 2, 0),
    "weather_outage": (calm, "all", 3, 0),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    routes = [parse_route(r) for r in load_fixture("tomtom_denver_slc.json")["routes"]]
    for name, (fn, failing, n_api, n_detours) in SCENARIOS.items():
        cache.clear()
        weather = FakeWeather(fn, fail_cells=set() if failing == "all" else set(failing))
        if failing == "all":
            weather.hourly = lambda cells, start, end: {}  # the provider returns nothing
        service = WeatherService(weather, cache, grid_deg=0.25, ttl_s=600, model="e2e")
        detours = [bent(routes[0], 1.2), bent(routes[0], -1.2)][:n_detours]
        planner = TripPlanner(FakeRouting(routes[:n_api], detours=detours), service, tare_lb=35_000)
        plan = planner.plan(TripRequest(DEN, SLC, DEPARTURE, 36_000, 25))
        body = plan_json(plan)
        body["generated_at"] = f"2026-10-18T13:00:00Z#{name}"  # stable but unique per scenario
        geoms = [decode_polyline(r["geometry"]) for r in body["routes"]]
        heat = heatmap_json(HeatmapBuilder(service, max_points=120).build(geoms, DEPARTURE, 36_000))
        (OUT / f"plan_{name}.json").write_text(json.dumps(body, indent=1))
        (OUT / f"heatmap_{name}.json").write_text(json.dumps(heat))
        print(
            name, "recommended", body["recommended_route_id"], "|", body["recommendation"]["reason"]
        )


if __name__ == "__main__":
    main()
