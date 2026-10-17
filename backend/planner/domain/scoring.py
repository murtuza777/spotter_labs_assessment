"""Turning checkpoint risk into miles per level for a whole route."""

from collections.abc import Sequence

from planner.domain.models import RiskLevel, RouteSummary


def owned_miles(checkpoint_miles: Sequence[float], route_length_mi: float) -> list[float]:
    """Miles each checkpoint represents.

    A checkpoint owns the stretch from the midpoint with its previous checkpoint to the
    midpoint with its next one; the first starts at mile 0 and the last ends at the
    destination. The shares add up exactly to the route length, so one bad checkpoint is
    never double-counted.
    """
    n = len(checkpoint_miles)
    if n == 0:
        return []
    if n == 1:
        return [route_length_mi]
    bounds = [0.0]
    for a, b in zip(checkpoint_miles, checkpoint_miles[1:], strict=False):
        bounds.append((a + b) / 2)
    bounds.append(route_length_mi)
    return [bounds[i + 1] - bounds[i] for i in range(n)]


def summarize(levels: Sequence[RiskLevel | None], miles: Sequence[float]) -> RouteSummary:
    """`levels[i]` is checkpoint i's risk (None when its weather is unknown)."""
    by_level = dict.fromkeys(RiskLevel, 0.0)
    unknown = 0.0
    for level, share in zip(levels, miles, strict=True):
        if level is None:
            unknown += share
        else:
            by_level[level] += share
    known = sum(by_level.values())
    avg = sum(int(level) * m for level, m in by_level.items()) / known if known else 0.0
    present = [lvl for lvl in levels if lvl is not None]
    return RouteSummary(
        miles_by_level=by_level,
        unknown_miles=unknown,
        avg_risk=avg,
        max_level=max(present) if present else None,
    )
