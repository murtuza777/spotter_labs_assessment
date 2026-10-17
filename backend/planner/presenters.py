"""Domain objects -> JSON-ready dicts (the API contract in docs/IMPLEMENTATION_PLAN.md 4.3)."""

from datetime import UTC, datetime

from planner.domain.geo import encode_polyline
from planner.domain.models import Checkpoint, RiskLevel
from planner.services.heatmap import Heatmap
from planner.services.plan_trip import PlannedRoute, TripPlan


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def plan_json(plan: TripPlan) -> dict:
    return {
        "generated_at": iso(datetime.now(UTC)),
        "request": {
            "origin": _place(plan.request.origin),
            "destination": _place(plan.request.destination),
            "departure_time": iso(plan.request.departure),
            "load_weight_lb": plan.request.load_lb,
            "sample_interval_mi": plan.request.interval_mi,
            "wind_metric": plan.request.wind_metric,
        },
        "recommended_route_id": plan.recommended_id,
        "recommendation": {
            # "recommended", "provisional" (no route has a complete forecast) or "none"
            # (every route has No Travel conditions; recommended_route_id is null).
            "status": plan.status.value,
            "route_id": plan.recommended_id,
            "reason": plan.reason,
            "exclusions": [{"route_id": e.route_id, "reason": e.reason} for e in plan.exclusions],
            "warnings": plan.warnings,
            "ranking": [
                "Severe miles",
                "High miles",
                "average risk",
                "travel time",
            ],
        },
        "routes": [_route(r) for r in plan.routes],
        "notices": plan.notices,
        "meta": plan.meta,
    }


def _place(place) -> dict:
    return {"label": place.label, "lat": place.lat, "lon": place.lon}


def _route(route: PlannedRoute) -> dict:
    s = route.scored.summary
    return {
        "id": route.id,
        "source": route.source,
        "rank": route.rank,
        "eligibility": route.eligibility,
        "waypoint": None
        if route.waypoint is None
        else {"lat": round(route.waypoint.lat, 5), "lon": round(route.waypoint.lon, 5)},
        "distance_mi": round(route.distance_mi, 1),
        "duration_s": round(route.scored.duration_s),
        "arrival_time": iso(route.arrival),
        "geometry": encode_polyline(route.geometry),
        "summary": {
            "miles_by_level": {lvl.slug: round(m, 1) for lvl, m in s.miles_by_level.items()},
            "unknown_miles": round(s.unknown_miles, 1),
            # Share of the route's miles that have a forecast (0-1).
            "forecast_coverage": round(1 - s.unknown_miles / route.distance_mi, 4)
            if route.distance_mi
            else 0.0,
            "avg_risk": round(s.avg_risk, 2),
            "max_level": s.max_level.slug if s.max_level is not None else None,
        },
        "segments": [
            {
                "level": seg.level.slug if seg.level is not None else None,
                "start_mile": round(seg.start_mile, 1),
                "end_mile": round(seg.end_mile, 1),
                "geometry": encode_polyline(seg.points),
            }
            for seg in route.segments
        ],
        "checkpoints": [_checkpoint(cp) for cp in route.scored.checkpoints],
    }


def _checkpoint(cp: Checkpoint) -> dict:
    w = cp.weather
    return {
        "index": cp.index,
        "mile": round(cp.mile, 1),
        "lat": round(cp.point.lat, 5),
        "lon": round(cp.point.lon, 5),
        "eta": iso(cp.eta),
        "forecast_hour": iso(cp.forecast_hour),
        # The forecast grid cell actually queried for this checkpoint.
        "weather_cell": None
        if cp.weather_cell is None
        else {"lat": cp.weather_cell.lat, "lon": cp.weather_cell.lon},
        "weather": None
        if w is None
        else {
            "wind_mph": round(w.wind_mph, 1),
            "gust_mph": round(w.gust_mph, 1),
            "rain_in_hr": round(w.rain_in_hr, 3),
            "snow_in_hr": round(w.snow_in_hr, 2),
        },
        "risk": None
        if cp.risk is None
        else {
            "level": cp.risk.level.slug,
            "score": int(cp.risk.level),
            "reasons": list(cp.risk.reasons),
            "factors": [
                {
                    "name": f.name,
                    "label": f.label,
                    "value": round(f.value, 3),
                    "unit": f.unit,
                    "base_level": f.base_level.slug,
                    "level": f.level.slug,
                    "load_rule": f.load_rule,
                }
                for f in cp.risk.factors
            ],
        },
    }


def heatmap_json(heatmap: Heatmap) -> dict:
    return {
        "hours": [iso(h) for h in heatmap.hours],
        "points": [[round(p.lat, 4), round(p.lon, 4)] for p in heatmap.points],
        "grid_step_deg": heatmap.grid_step_deg,
        "levels": [lvl.slug for lvl in RiskLevel],
        "frames": heatmap.frames,
        "meta": heatmap.meta,
    }
