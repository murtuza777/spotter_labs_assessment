"""Choosing the recommended route.

Ranking is exactly the assessment's order, lexicographic, lower is better:
  1. Severe miles
  2. High miles
  3. Average risk
  4. Travel time
Miles are compared at 0.1 mi and average risk at 0.01, so float noise counts as a tie and the
next criterion decides. Travel time only breaks ties once the risk is equal, so a shorter
route can never beat one with fewer Severe miles. Full ties keep the provider's order.

Safety is a separate, explicit constraint applied *before* ranking, not an extra criterion:
  - A route with any No Travel miles is not eligible: it is never recommended.
  - A route with miles that have no forecast can't be confirmed safe. It is only recommended
    "provisionally", only when no fully forecast route without No Travel exists, and only if
    at least half its miles have a forecast (below that there is too little data to rank on).
  - If no route qualifies, nothing is recommended, and the reason says whether that is
    because of No Travel conditions or because the weather data was unavailable.
Excluded routes are still shown, each with the reason it was excluded.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from planner.domain.models import ScoredRoute

# Unknown stretches shorter than this (float noise) don't count as missing forecast.
UNKNOWN_TOLERANCE_MI = 0.05
# Below this share of forecast miles a route can't even be a provisional pick.
MIN_PROVISIONAL_COVERAGE = 0.5


class Eligibility(StrEnum):
    ELIGIBLE = "eligible"
    INCOMPLETE_FORECAST = "incomplete_forecast"  # some miles lack a forecast
    INSUFFICIENT_FORECAST = "insufficient_forecast"  # under half the miles have one
    NO_TRAVEL = "no_travel"


class Status(StrEnum):
    RECOMMENDED = "recommended"
    PROVISIONAL = "provisional"
    NONE = "none"


def forecast_coverage(route: ScoredRoute) -> float:
    s = route.summary
    known = sum(s.miles_by_level.values())
    total = known + s.unknown_miles
    return known / total if total > 0 else 0.0


def eligibility(route: ScoredRoute) -> Eligibility:
    s = route.summary
    if s.no_travel_miles > 0:
        return Eligibility.NO_TRAVEL
    if s.unknown_miles > UNKNOWN_TOLERANCE_MI:
        if forecast_coverage(route) < MIN_PROVISIONAL_COVERAGE:
            return Eligibility.INSUFFICIENT_FORECAST
        return Eligibility.INCOMPLETE_FORECAST
    return Eligibility.ELIGIBLE


def _hm(seconds: float) -> str:
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours}h {minutes:02d}m"


@dataclass(frozen=True, slots=True)
class _Criterion:
    label: str
    key: Callable[[ScoredRoute], float]
    show: Callable[[ScoredRoute], str]


# The assessment's ranking, in order. Nothing else is ranked on.
CRITERIA: tuple[_Criterion, ...] = (
    _Criterion(
        "Severe miles",
        lambda r: round(r.summary.severe_miles, 1),
        lambda r: f"{r.summary.severe_miles:,.1f} mi",
    ),
    _Criterion(
        "High miles",
        lambda r: round(r.summary.high_miles, 1),
        lambda r: f"{r.summary.high_miles:,.1f} mi",
    ),
    _Criterion(
        "average risk",
        lambda r: round(r.summary.avg_risk, 2),
        lambda r: f"{r.summary.avg_risk:.2f}",
    ),
    _Criterion("travel time", lambda r: r.duration_s, lambda r: _hm(r.duration_s)),
)


def sort_key(route: ScoredRoute) -> tuple[float, ...]:
    return tuple(c.key(route) for c in CRITERIA)


def rank(routes: Sequence[ScoredRoute]) -> list[ScoredRoute]:
    """The assessment's ranking. Best first; full ties keep the input (provider) order."""
    return sorted(routes, key=sort_key)


def deciding_criterion(winner: ScoredRoute, other: ScoredRoute) -> str | None:
    """'on Severe miles (0.0 mi vs 18.0 mi)': the first criterion where `winner` beats `other`."""
    for criterion in CRITERIA:
        if criterion.key(winner) < criterion.key(other):
            return f"on {criterion.label} ({criterion.show(winner)} vs {criterion.show(other)})"
    return None


@dataclass(frozen=True, slots=True)
class Exclusion:
    route_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Recommendation:
    status: Status
    route_id: str | None
    # Status NONE only: "no_travel" (every route has it) or "no_forecast" (data unavailable).
    none_reason: str | None
    # Display order: eligible routes (ranked), then incomplete-forecast, then No Travel.
    order: list[ScoredRoute]
    reason: str
    exclusions: list[Exclusion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def recommend(routes: Sequence[ScoredRoute]) -> Recommendation:
    groups = {e: rank([r for r in routes if eligibility(r) == e]) for e in Eligibility}
    order = (
        groups[Eligibility.ELIGIBLE]
        + groups[Eligibility.INCOMPLETE_FORECAST]
        + groups[Eligibility.INSUFFICIENT_FORECAST]
        + groups[Eligibility.NO_TRAVEL]
    )
    if groups[Eligibility.ELIGIBLE]:
        status, pool = Status.RECOMMENDED, groups[Eligibility.ELIGIBLE]
    elif groups[Eligibility.INCOMPLETE_FORECAST]:
        status, pool = Status.PROVISIONAL, groups[Eligibility.INCOMPLETE_FORECAST]
    else:
        status, pool = Status.NONE, []

    best = pool[0] if pool else None
    in_pool = {id(r) for r in pool}
    exclusions = [_exclusion(r) for r in order if id(r) not in in_pool]
    warnings: list[str] = []
    none_reason = None
    if status is Status.NONE and len(groups[Eligibility.NO_TRAVEL]) == len(order):
        none_reason = "no_travel"
        reason = "No route is recommended: every route has No Travel conditions."
        warnings.append(
            "Every route has No Travel conditions at this departure time. "
            "Consider delaying the trip."
        )
    elif status is Status.NONE:
        none_reason = "no_forecast"
        reason = (
            "No route is recommended: weather forecasts were unavailable for most of every "
            "route that is free of No Travel conditions, so the risk can't be assessed."
        )
        warnings.append(
            "Weather data was unavailable for most of the trip. Try again in a few minutes."
        )
    else:
        reason = _explain(best, pool)
    if status is Status.PROVISIONAL:
        warnings.append(
            f"No route has a complete forecast. Route {best.id} is a provisional pick based on "
            f"the forecast miles only; {best.summary.unknown_miles:,.1f} mi have no forecast, "
            "so check conditions there before driving."
        )
    return Recommendation(
        status=status,
        route_id=best.id if best else None,
        none_reason=none_reason,
        order=order,
        reason=reason,
        exclusions=exclusions,
        warnings=warnings,
    )


def _explain(best: ScoredRoute, pool: Sequence[ScoredRoute]) -> str:
    others = [r for r in pool if r is not best]
    if not others:
        return f"Route {best.id} is the only eligible route."
    clauses = []
    for other in others:
        why = deciding_criterion(best, other)
        clauses.append(f"Route {other.id} {why}" if why else f"ties Route {other.id}")
    joined = clauses[0] if len(clauses) == 1 else ", ".join(clauses[:-1]) + " and " + clauses[-1]
    if all(deciding_criterion(best, o) is None for o in others):
        return f"Route {best.id} {joined} on every criterion; keeping the routing provider's order."
    return f"Route {best.id} beats {joined}."


def _exclusion(route: ScoredRoute) -> Exclusion:
    s = route.summary
    if eligibility(route) is Eligibility.NO_TRAVEL:
        why = f"No Travel conditions on {s.no_travel_miles:,.1f} mi (safety constraint)"
    elif eligibility(route) is Eligibility.INSUFFICIENT_FORECAST:
        why = (
            f"no forecast for {s.unknown_miles:,.1f} mi ({1 - forecast_coverage(route):.0%} of "
            "the route), too little to assess"
        )
    else:
        why = f"no forecast for {s.unknown_miles:,.1f} mi, so it can't be confirmed safe"
    return Exclusion(route.id, f"Route {route.id} is not eligible: {why}.")
