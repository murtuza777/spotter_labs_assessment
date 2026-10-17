import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.core.cache import cache

from planner.domain.models import LatLon
from planner.providers.base import HourlySeries, RouteOption
from planner.providers.tomtom import parse_route

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tomtom_routes() -> list[RouteOption]:
    return [parse_route(r) for r in load_fixture("tomtom_denver_slc.json")["routes"]]


class FakeRouting:
    """Returns canned routes; records every call."""

    def __init__(self, main: list[RouteOption], detours: list[RouteOption] | None = None):
        self.main = main
        self.detours = list(detours or [])
        self.calls: list[dict] = []

    def routes(
        self, origin, destination, *, depart_at, vehicle_weight_kg, max_alternatives=0, via=None
    ):
        self.calls.append(
            {"via": via, "max_alternatives": max_alternatives, "weight": vehicle_weight_kg}
        )
        if via is None:
            return list(self.main)
        return [self.detours.pop(0)] if self.detours else []


class FakeWeather:
    """Synthetic hourly weather: `fn(cell, hour) -> (wind, gust, rain, snow)`."""

    def __init__(self, fn, fail_cells: set[LatLon] | None = None):
        self.fn = fn
        self.fail_cells = fail_cells or set()
        self.requested: list[LatLon] = []

    def hourly(self, cells, start, end):
        self.requested.extend(cells)
        hours = int((end - start).total_seconds() // 3600) + 1
        out = {}
        for cell in cells:
            if cell in self.fail_cells:
                continue
            rows = [self.fn(cell, start + timedelta(hours=h)) for h in range(hours)]
            out[cell] = HourlySeries(
                start=start,
                wind_mph=[r[0] for r in rows],
                gust_mph=[r[1] for r in rows],
                rain_in_hr=[r[2] for r in rows],
                snow_in_hr=[r[3] for r in rows],
            )
        return out


def calm(cell, hour):
    return (8.0, 12.0, 0.0, 0.0)


@pytest.fixture
def departure() -> datetime:
    return (datetime.now(UTC) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
