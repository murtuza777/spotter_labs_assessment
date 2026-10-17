"""Trip planning: routes -> checkpoints -> ETAs -> weather -> risk -> ranking."""

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from planner.domain.eta import TimeProfile
from planner.domain.geo import (
    METERS_PER_MILE,
    cumulative_miles,
    haversine_mi,
    interpolate_along,
    route_similarity,
    shared_fraction,
    simplify,
    slice_polyline,
)
from planner.domain.models import Checkpoint, LatLon, RiskLevel, ScoredRoute
from planner.domain.recommend import Exclusion, Status, eligibility, recommend
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

# Two routes sharing at least this much road (see geo.route_similarity) are the same route.
DUPLICATE_SIMILARITY = 0.95
# A waypoint detour is only offered if it is genuinely different and still a reasonable trip.
DETOUR_MAX_SIMILARITY = 0.85
DETOUR_MAX_DISTANCE_RATIO = 1.4
DETOUR_MAX_DURATION_RATIO = 1.5
# Waypoint placement: perpendicular to the origin->destination line at the main route's
# midpoint, offset by this share of the straight-line distance, clamped to [min, max] miles.
DETOUR_OFFSET_SHARE = 0.15
DETOUR_OFFSET_MIN_MI = 15.0
DETOUR_OFFSET_MAX_MI = 100.0


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
    eligibility: str = "eligible"
    waypoint: LatLon | None = None  # detours only: the waypoint TomTom was asked to pass


@dataclass(slots=True)
class TripPlan:
    request: TripRequest
    routes: list[PlannedRoute]
    recommended_id: str | None  # None when every route has No Travel conditions
    status: Status
    reason: str
    exclusions: list[Exclusion]
    warnings: list[str]
    notices: list[str]
    # Request accounting: provider calls, weather cache use and timings (also logged).
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Candidate:
    option: RouteOption
    source: str  # "routing_api" or "detour"
    via: LatLon | None = None


@dataclass(slots=True)
class _Prepared:
    option: RouteOption
    source: str
    via: LatLon | None
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
        t0 = time.perf_counter()
        options, notices, routing_lookups = self._candidate_routes(req)
        routing_ms = round((time.perf_counter() - t0) * 1000)
        prepared = [self._prepare(c, req) for c in options]

        all_cps = [cp for p in prepared for cp in p.checkpoints]
        series, weather_stats = self._weather.series_with_stats(
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
                    eligibility=eligibility(scored).value,
                    waypoint=prep.via,
                )
            )

        rec = recommend([r.scored for r in routes])
        order = {s.id: i + 1 for i, s in enumerate(rec.order)}
        for r in routes:
            r.rank = order[r.id]
        meta = {
            "routing_lookups": routing_lookups,
            "routing_ms": routing_ms,
            "checkpoints": len(all_cps),
            "weather": weather_stats.as_dict(),
            "total_ms": round((time.perf_counter() - t0) * 1000),
        }
        log.info(
            "plan routes=%d sources=%s routing_lookups=%d checkpoints=%d weather=%s "
            "routing_ms=%d total_ms=%d",
            len(routes),
            ",".join(r.source for r in routes),
            routing_lookups,
            len(all_cps),
            weather_stats.as_dict(),
            routing_ms,
            meta["total_ms"],
        )
        return TripPlan(
            request=req,
            routes=routes,
            recommended_id=rec.route_id,
            status=rec.status,
            reason=rec.reason,
            exclusions=rec.exclusions,
            warnings=rec.warnings,
            notices=notices,
            meta=meta,
        )

    # -- routes ---------------------------------------------------------------------------

    def _candidate_routes(self, req: TripRequest) -> tuple[list[_Candidate], list[str], int]:
        """Up to 3 distinct routes, the notices to show about them, and the routing lookups made
        (calls into the routing layer; repeats within the route-cache TTL never reach TomTom).

        TomTom alternatives come first; one sharing >= 95 % of its road with an earlier one is
        the same route and is dropped. Only if fewer than 3 distinct routes remain do we ask
        TomTom for a route through a waypoint on either side of the main route (see
        `_detour_points`). Those are real TomTom truck routes, kept only if they are distinct,
        reasonable and don't double back (`_detour_rejection`), and labelled "detour"
        everywhere they appear. Nothing is synthesized: if no detour qualifies, fewer routes
        are shown with a notice saying why.
        """
        weight_kg = round((req.load_lb + self._tare_lb) * LB_TO_KG)
        calls = 0

        def call(via: LatLon | None = None, alternatives: int = 0) -> list[RouteOption]:
            nonlocal calls
            calls += 1
            return self._routing.routes(
                req.origin.point,
                req.destination.point,
                depart_at=req.departure,
                vehicle_weight_kg=weight_kg,
                max_alternatives=alternatives,
                via=via,
            )

        provider = call(alternatives=TARGET_ROUTES - 1)
        found: list[_Candidate] = []
        for option in provider:
            if len(found) < TARGET_ROUTES and not any(
                route_similarity(option.points, c.option.points) >= DUPLICATE_SIMILARITY
                for c in found
            ):
                found.append(_Candidate(option, "routing_api"))
        if not found:
            raise ProviderError(
                "no_route", "No truck route was found between those places.", status=422
            )

        notices: list[str] = []
        if len(found) >= TARGET_ROUTES:
            return found, notices, calls

        api_count = len(found)
        duplicates = len(provider) - api_count
        fastest = min(found, key=lambda c: c.option.duration_s).option
        vias = _detour_points(found[0].option.points)
        with ThreadPoolExecutor(max_workers=len(vias)) as pool:
            results = list(pool.map(lambda via: _safe(lambda: call(via=via)), vias))
        rejected: list[str] = []
        for via, options in zip(vias, results, strict=True):
            if len(found) >= TARGET_ROUTES:
                break
            if not options:
                rejected.append("TomTom found no truck route through a waypoint")
                continue
            why = _detour_rejection(options[0], via, found, fastest)
            if why:
                rejected.append(why)
            else:
                found.append(_Candidate(options[0], "detour", via))

        provider_note = f"TomTom returned {api_count} distinct truck route(s)"
        if duplicates:
            verb = "was" if duplicates == 1 else "were"
            provider_note += f" ({duplicates} more {verb} the same road)"
        detour_ids = [ROUTE_IDS[i] for i, c in enumerate(found) if c.source == "detour"]
        if detour_ids:
            noun = "is a detour" if len(detour_ids) == 1 else "are detours"
            notices.append(
                f"{provider_note}. Route {' and '.join(detour_ids)} {noun}: TomTom truck "
                "routing through a waypoint this app placed beside the main route's midpoint "
                "(shown on the map). It is a real drivable route, but not one TomTom offered "
                "as an alternative."
            )
        if len(found) < TARGET_ROUTES:
            reasons = "; ".join(dict.fromkeys(rejected)) or "no waypoint routes were possible"
            notices.append(
                f"Only {len(found)} meaningful route(s) could be found. {provider_note}, and "
                f"no waypoint detour qualified: {reasons}."
            )
        return found, notices, calls

    # -- checkpoints ----------------------------------------------------------------------

    def _prepare(self, candidate: _Candidate, req: TripRequest) -> _Prepared:
        option = candidate.option
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
        return _Prepared(
            option, candidate.source, candidate.via, cum, scale, official_mi, checkpoints
        )


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


def _detour_rejection(
    option: RouteOption, via: LatLon, existing: list[_Candidate], fastest: RouteOption
) -> str | None:
    """Why a waypoint route is not a meaningful extra option, or None if it is."""
    distance_ratio = option.length_m / fastest.length_m
    duration_ratio = option.duration_s / fastest.duration_s
    if distance_ratio > DETOUR_MAX_DISTANCE_RATIO:
        return f"a detour would be {distance_ratio:.2f}x the fastest route's distance"
    if duration_ratio > DETOUR_MAX_DURATION_RATIO:
        return f"a detour would take {duration_ratio:.2f}x the fastest route's drive time"
    if any(
        route_similarity(option.points, c.option.points) > DETOUR_MAX_SIMILARITY for c in existing
    ):
        return "a detour would mostly repeat an existing route"
    if _doubles_back(option.points, via):
        return "a detour would drive out to the waypoint and back on the same road"
    return None


def _doubles_back(points: list[LatLon], via: LatLon, *, window_mi: float = 10.0) -> bool:
    """True if the route reaches the waypoint on a spur: the 10 mi before it and the 10 mi
    after it are mostly the same road (an out-and-back, not a through route)."""
    cum = cumulative_miles(points)
    k = min(range(len(points)), key=lambda i: haversine_mi(points[i], via))
    at = cum[k]
    if at < window_mi or cum[-1] - at < window_mi:
        return False
    before = slice_polyline(points, cum, at - window_mi, at)
    after = slice_polyline(points, cum, at, at + window_mi)
    return shared_fraction(before, after) > 0.5


def _detour_points(points: list[LatLon]) -> list[LatLon]:
    """Two waypoints, one on each side of the main route's midpoint.

    Each sits perpendicular to the origin->destination line, offset by 15 % of the
    straight-line distance (clamped to 15-100 mi). That nudges TomTom onto a different
    corridor for the middle of the trip while keeping its ends; TomTom snaps the waypoint to
    the nearest truck-accessible road.
    """
    cum = cumulative_miles(points)
    mid = interpolate_along(points, cum, cum[-1] / 2)
    a, b = points[0], points[-1]
    straight = haversine_mi(a, b)
    offset_mi = min(DETOUR_OFFSET_MAX_MI, max(DETOUR_OFFSET_MIN_MI, DETOUR_OFFSET_SHARE * straight))

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
