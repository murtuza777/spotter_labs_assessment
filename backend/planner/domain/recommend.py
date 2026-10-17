"""Ranking routes and explaining the pick.

Order (docs/IMPLEMENTATION_PLAN.md section 2.5), lexicographic, lower is better:
  1. No Travel miles   - not in the brief's list, but No Travel is worse than Severe, so a
                         route with known No Travel miles must never beat one without.
  2. Forecast coverage - a fully forecast route ranks ahead of one with unforecast miles.
                         Unknown miles are not scored, so without this gate a route whose
                         weather could not be fetched would look as safe as calm weather.
  3. Severe miles      - from here on, exactly the brief's order
  4. High miles
  5. Average risk
  6. Travel time
Miles are compared at 0.1 mi and average risk at 0.01 so float noise counts as a tie and the
next criterion decides. This is how the brief's "balance weather risk and travel time" plays
out: travel time only breaks ties once the risk is equal, so a shorter route can never beat
one with fewer Severe miles.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from planner.domain.models import ScoredRoute

# Unknown stretches shorter than this (float noise) don't count against coverage.
UNKNOWN_TOLERANCE_MI = 0.05


def _hm(seconds: float) -> str:
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours}h {minutes:02d}m"


def _has_unknown(route: ScoredRoute) -> bool:
    return route.summary.unknown_miles > UNKNOWN_TOLERANCE_MI


@dataclass(frozen=True, slots=True)
class _Criterion:
    label: str
    key: Callable[[ScoredRoute], float]
    show: Callable[[ScoredRoute], str]


_CRITERIA: tuple[_Criterion, ...] = (
    _Criterion(
        "No Travel miles",
        lambda r: round(r.summary.no_travel_miles, 1),
        lambda r: f"{r.summary.no_travel_miles:,.1f} mi",
    ),
    _Criterion(
        "forecast coverage",
        lambda r: 1.0 if _has_unknown(r) else 0.0,
        lambda r: (
            f"{r.summary.unknown_miles:,.1f} mi unforecast" if _has_unknown(r) else "complete"
        ),
    ),
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
    return tuple(c.key(route) for c in _CRITERIA)


def rank(routes: Sequence[ScoredRoute]) -> list[ScoredRoute]:
    """Best first. Ties on every criterion keep the routing API's order (deterministic)."""
    return sorted(routes, key=sort_key)


def deciding_criterion(winner: ScoredRoute, other: ScoredRoute) -> str | None:
    """'on Severe miles (0.0 mi vs 18.0 mi)': the first criterion where `winner` beats `other`."""
    for criterion in _CRITERIA:
        mine, theirs = criterion.key(winner), criterion.key(other)
        if mine < theirs:
            return f"on {criterion.label} ({criterion.show(winner)} vs {criterion.show(other)})"
    return None


def explain(ranked: Sequence[ScoredRoute]) -> str:
    """Why ranked[0] won, against every other route, e.g.
    'Route B beats Route C on travel time (8h 01m vs 8h 59m) and Route A on average risk
    (0.00 vs 0.14).'"""
    if not ranked:
        return ""
    best = ranked[0]
    if len(ranked) == 1:
        return f"Route {best.id} is the only route available."
    clauses = []
    for other in ranked[1:]:
        reason = deciding_criterion(best, other)
        clauses.append(
            f"Route {other.id} {reason}" if reason else f"ties Route {other.id} on every criterion"
        )
    joined = clauses[0] if len(clauses) == 1 else ", ".join(clauses[:-1]) + " and " + clauses[-1]
    if all(deciding_criterion(best, o) is None for o in ranked[1:]):
        return f"Route {best.id} {joined}; keeping the routing API's first choice."
    return f"Route {best.id} beats {joined}."


def warnings(ranked: Sequence[ScoredRoute]) -> list[str]:
    """Safety caveats about the recommendation. `ranked[0]` is the recommended route."""
    if not ranked:
        return []
    best = ranked[0]
    out: list[str] = []
    if best.summary.no_travel_miles > 0:
        # No Travel is ranked first, so this means every route has No Travel conditions.
        out.append(
            f"Every route has No Travel conditions at this departure time. Route {best.id} is "
            f"only the least risky option ({best.summary.no_travel_miles:,.1f} mi of No Travel). "
            "Consider delaying the trip."
        )
    if _has_unknown(best):
        out.append(
            f"No forecast was available for {best.summary.unknown_miles:,.1f} mi of Route "
            f"{best.id}; those miles are unscored, so check conditions there before driving."
        )
    elif any(_has_unknown(r) for r in ranked[1:]):
        out.append(
            "Some miles on other routes had no forecast; those routes were ranked after fully "
            "forecast ones."
        )
    return out
