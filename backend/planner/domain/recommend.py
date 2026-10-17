"""Ranking routes and explaining the pick.

Order (plan section 2.5), lexicographic, lower is better:
  1. No Travel miles  - not in the brief's list, but No Travel is worse than Severe, so a
                        route with No Travel miles must never beat one without
  2. Severe miles
  3. High miles
  4. Average risk
  5. Travel time
Miles are compared at 0.1 mi and average risk at 0.01 so float noise counts as a tie and the
next criterion decides. This is how the brief's "balance weather risk and travel time" plays
out: travel time breaks ties once the risk is equal.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from planner.domain.models import ScoredRoute


@dataclass(frozen=True, slots=True)
class _Criterion:
    label: str
    unit: str

    def describe(self, value: float) -> str:
        if self.unit == "mi":
            return f"{value:,.1f} {self.label}"
        if self.unit == "score":
            return f"average risk {value:.2f}"
        hours, minutes = divmod(round(value / 60), 60)
        return f"{hours}h {minutes:02d}m"


_CRITERIA = (
    _Criterion("No Travel miles", "mi"),
    _Criterion("Severe miles", "mi"),
    _Criterion("High miles", "mi"),
    _Criterion("average risk", "score"),
    _Criterion("travel time", "s"),
)


def sort_key(route: ScoredRoute) -> tuple[float, float, float, float, float]:
    s = route.summary
    return (
        round(s.no_travel_miles, 1),
        round(s.severe_miles, 1),
        round(s.high_miles, 1),
        round(s.avg_risk, 2),
        route.duration_s,
    )


def rank(routes: Sequence[ScoredRoute]) -> list[ScoredRoute]:
    """Best first. Ties on every criterion keep the routing API's order."""
    return sorted(routes, key=sort_key)


def explain(ranked: Sequence[ScoredRoute]) -> str:
    """Why ranked[0] won: the first criterion where it beats the runner-up."""
    if not ranked:
        return ""
    best = ranked[0]
    if len(ranked) == 1:
        return f"Route {best.id} is the only route available."
    runner = ranked[1]
    for criterion, mine, theirs in zip(_CRITERIA, sort_key(best), sort_key(runner), strict=True):
        if mine < theirs:
            return (
                f"Route {best.id}: {criterion.describe(mine)} vs "
                f"{criterion.describe(theirs)} on Route {runner.id}"
            )
    return f"Routes {best.id} and {runner.id} tie on every criterion; keeping Route {best.id}."


def warnings(routes: Sequence[ScoredRoute]) -> list[str]:
    out: list[str] = []
    if routes and all(r.summary.no_travel_miles > 0 for r in routes):
        out.append(
            "Every route has No Travel conditions at this departure time. "
            "Consider delaying the trip."
        )
    if any(r.summary.unknown_miles > 0 for r in routes):
        out.append("Weather was unavailable for part of the trip; those miles are not scored.")
    return out
