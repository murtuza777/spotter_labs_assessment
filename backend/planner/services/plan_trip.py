"""Trip planning: routes -> checkpoints -> ETAs -> weather -> risk -> ranking."""

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from planner.domain.eta import TimeProfile
from planner.domain.geo import (
    METERS_PER_MILE,
    cumulative_miles,
    haversine_mi,
    interpolate_along,
    resample,
    simplify,
    slice_polyline,
    snap,
)
from planner.domain.models import Checkpoint, LatLon, RiskLevel, ScoredRoute
from planner.domain.recommend import explain, rank, warnings
from planner.domain.risk import assess
from planner.domain.sampling import checkpoint_miles
from planner.domain.scoring import owned_miles, summarize
from planner.domain.timebucket import forecast_hour_for
from planner.providers.base import Place, ProviderError, RouteOption, RoutingProvider
from planner.services.weather import WeatherService, sample

log = logging.getLogger(__name__)

LB_TO_KG = 0.45359237
ROUTE_IDS = ("A", "B", "C")
TARGET_ROUTES = 3
DISPLAY_TOLERANCE_M = 30
_OVERLAP_CELL_DEG = 0.05
_DUPLICATE_OVERLAP = 0.9


@dataclass(frozen=True, slots=True)
class TripRequest:
    origin: Place
    destination: Place
    departure: datetime
    load_lb: float
    interval_mi: int
    wind_metric: str = "gust"


@dataclass(frozen=True, slots=True)
class RiskSegment:
    level: RiskLevel | None
    start_mile: float
    end_mile: float
    points: list[LatLon]


@dataclass(slots=True)
class PlannedRoute:
    id: str
    source: str  # "routing_api" or "detour"
    distance_mi: float
    arrival: datetime
    geometry: list[LatLon]
    scored: ScoredRoute
    segments: list[RiskSegment] = field(default_factory=list)
    rank: int = 0


@dataclass(slots=True)
class TripPlan:
    request: TripRequest
    routes: list[PlannedRoute]
    recommended_id: str
    reason: str
    warnings: list[str]
    notices: list[str]


@dataclass(slots=True)
class _Prepared:
    option: RouteOption
    source: str
    cum: list[float]
    scale: float  # official miles per polyline mile
    distance_mi: float
    checkpoints: list[Checkpoint]


class TripPlanner:
    def __init__(self, routing: RoutingProvider, weather: WeatherService, *, tare_lb: float):
        self._routing = routing
        self._weather = weather
        self._tare_lb = tare_lb

    def plan(self, req: TripRequest) -> TripPlan:
        options, notices = self._candidate_routes(req)
        prepared = [self._prepare(opt, src, req) for opt, src in options]

        all_cps = [cp for p in prepared for cp in p.checkpoints]
        series = self._weather.series_for(
            (cp.weather_cell for cp in all_cps if cp.weather_cell),
            min(cp.forecast_hour for cp in all_cps),
            max(cp.forecast_hour for cp in all_cps),
        )

        routes: list[PlannedRoute] = []
        for rid, prep in zip(ROUTE_IDS, prepared, strict=False):
            for cp in prep.checkpoints:
                cp.weather = sample(series, cp.weather_cell, cp.forecast_hour)
                cp.risk = assess(cp.weather, req.load_lb, req.wind_metric) if cp.weather else None
            levels = [cp.risk.level if cp.risk else None for cp in prep.checkpoints]
            summary = summarize(levels, [cp.owned_miles for cp in prep.checkpoints])
            scored = ScoredRoute(
                id=rid,
                duration_s=prep.option.duration_s,
                summary=summary,
                checkpoints=prep.checkpoints,
            )
            routes.append(
                PlannedRoute(
                    id=rid,
                    source=prep.source,
                    distance_mi=prep.distance_mi,
                    arrival=req.departure + timedelta(seconds=prep.option.duration_s),
                    geometry=simplify(prep.option.points, DISPLAY_TOLERANCE_M),
                    scored=scored,
                    segments=_risk_segments(prep),
                )
            )

        ranked = rank([r.scored for r in routes])
        order = {s.id: i + 1 for i, s in enumerate(ranked)}
        for r in routes:
            r.rank = order[r.id]
        return TripPlan(
            request=req,
            routes=routes,
            recommended_id=ranked[0].id,
            reason=explain(ranked),
            warnings=warnings([r.scored for r in routes]),
            notices=notices,
        )

    # -- routes ---------------------------------------------------------------------------

    def _candidate_routes(
        self, req: TripRequest
    ) -> tuple[list[tuple[RouteOption, str]], list[str]]:
        weight_kg = round((req.load_lb + self._tare_lb) * LB_TO_KG)

        def call(via: LatLon | None = None, alternatives: int = 0) -> list[RouteOption]:
            return self._routing.routes(
                req.origin.point,
                req.destination.point,
                depart_at=req.departure,
                vehicle_weight_kg=weight_kg,
                max_alternatives=alternatives,
                via=via,
            )

        found: list[tuple[RouteOption, str]] = []
        signatures: list[set[tuple[float, float]]] = []

        def add(option: RouteOption, source: str) -> None:
            if len(found) >= TARGET_ROUTES or len(option.points) < 2:
                return
            sig = _signature(option.points)
            if any(_overlap(sig, other) > _DUPLICATE_OVERLAP for other in signatures):
                return
            found.append((option, source))
            signatures.append(sig)

        for option in call(alternatives=TARGET_ROUTES - 1):
            add(option, "routing_api")
        if not found:
            raise ProviderError(
                "no_route", "No truck route was found between those places.", status=422
            )

        notices: list[str] = []
        if len(found) < TARGET_ROUTES:
            detours = _detour_points(found[0][0].points)
            with ThreadPoolExecutor(max_workers=len(detours)) as pool:
                results = list(pool.map(lambda via: _safe(lambda: call(via=via)), detours))
            for options in results:
                for option in options[:1]:
                    add(option, "detour")
            if any(src == "detour" for _, src in found):
                notices.append(
                    "The routing API returned fewer than 3 distinct truck routes, so the extra "
                    "option(s) were generated through a detour waypoint."
                )
            if len(found) < TARGET_ROUTES:
                notices.append(f"Only {len(found)} distinct truck route(s) exist for this trip.")
        return found, notices

    # -- checkpoints ----------------------------------------------------------------------

    def _prepare(self, option: RouteOption, source: str, req: TripRequest) -> _Prepared:
        points = option.points
        cum = cumulative_miles(points)
        poly_len = cum[-1]
        official_mi = option.length_m / METERS_PER_MILE
        scale = official_mi / poly_len if poly_len > 0 else 1.0

        samples = [(0.0, 0.0), (poly_len, option.duration_s)]
        samples += [
            (cum[min(p.point_index, len(cum) - 1)], p.travel_time_s) for p in option.progress
        ]
        profile = TimeProfile(samples) if poly_len > 0 else None

        miles = checkpoint_miles(official_mi, req.interval_mi)
        shares = owned_miles(miles, official_mi)
        checkpoints = []
        for i, (mile, share) in enumerate(zip(miles, shares, strict=True)):
            along = mile / scale
            point = interpolate_along(points, cum, along)
            elapsed = profile.seconds_at(along) if profile else 0.0
            eta = req.departure + timedelta(seconds=elapsed)
            checkpoints.append(
                Checkpoint(
                    index=i,
                    mile=mile,
                    point=point,
                    eta=eta,
                    forecast_hour=forecast_hour_for(eta),
                    weather_cell=self._weather.cell_for(point),
                    owned_miles=share,
                )
            )
        return _Prepared(option, source, cum, scale, official_mi, checkpoints)


def _risk_segments(prep: _Prepared) -> list[RiskSegment]:
    """Consecutive checkpoints with the same level merged into one drawable stretch."""
    segments: list[RiskSegment] = []
    start = 0.0
    for cp in prep.checkpoints:
        end = start + cp.owned_miles
        level = cp.risk.level if cp.risk else None
        if segments and segments[-1].level == level:
            prev = segments[-1]
            segments[-1] = RiskSegment(level, prev.start_mile, end, [])
        else:
            segments.append(RiskSegment(level, start, end, []))
        start = end
    points = prep.option.points
    return [
        RiskSegment(
            s.level,
            s.start_mile,
            s.end_mile,
            simplify(
                slice_polyline(
                    points, prep.cum, s.start_mile / prep.scale, s.end_mile / prep.scale
                ),
                DISPLAY_TOLERANCE_M,
            ),
        )
        for s in segments
    ]


def _signature(points: list[LatLon]) -> set[tuple[float, float]]:
    return {
        (snap(p.lat, _OVERLAP_CELL_DEG), snap(p.lon, _OVERLAP_CELL_DEG))
        for p in resample(points, 5)
    }


def _overlap(a: set, b: set) -> float:
    return len(a & b) / max(1, min(len(a), len(b)))


def _detour_points(points: list[LatLon]) -> list[LatLon]:
    """Two waypoints off either side of the main route's midpoint."""
    cum = cumulative_miles(points)
    mid = interpolate_along(points, cum, cum[-1] / 2)
    a, b = points[0], points[-1]
    straight = haversine_mi(a, b)
    offset_mi = min(100.0, max(15.0, 0.15 * straight))

    cos_lat = math.cos(math.radians(mid.lat))
    dx = (b.lon - a.lon) * cos_lat
    dy = b.lat - a.lat
    norm = math.hypot(dx, dy) or 1.0
    # Unit vector perpendicular to origin->destination, in (east, north) degrees.
    px, py = -dy / norm, dx / norm
    deg = offset_mi / 69.0
    return [
        LatLon(mid.lat + side * py * deg, mid.lon + side * px * deg / max(cos_lat, 0.2))
        for side in (1, -1)
    ]


def _safe(fn) -> list[RouteOption]:
    try:
        return fn()
    except ProviderError as exc:
        log.info("detour route failed: %s", exc.code)
        return []
