import itertools

import pytest

from planner.domain.models import RiskLevel as L
from planner.domain.models import RouteSummary, ScoredRoute
from planner.domain.recommend import (
    CRITERIA,
    Eligibility,
    Status,
    eligibility,
    rank,
    recommend,
    sort_key,
)


def _route(
    rid: str,
    *,
    nt: float = 0,
    severe: float = 0,
    high: float = 0,
    avg: float = 0.0,
    hours: float = 5,
    unknown: float = 0,
) -> ScoredRoute:
    miles = dict.fromkeys(L, 0.0)
    miles.update({L.NO_TRAVEL: nt, L.SEVERE: severe, L.HIGH: high, L.LOW: 100})
    summary = RouteSummary(
        miles_by_level=miles, unknown_miles=unknown, avg_risk=avg, max_level=L.LOW
    )
    return ScoredRoute(id=rid, duration_s=hours * 3600, summary=summary)


def _ids(routes) -> list[str]:
    return [r.id for r in routes]


# --- The assessment's ranking, exactly -------------------------------------------------


def test_ranking_criteria_are_exactly_the_assessments() -> None:
    labels = [c.label for c in CRITERIA]
    assert labels == ["Severe miles", "High miles", "average risk", "travel time"]
    assert len(sort_key(_route("A"))) == 4


def test_fewest_severe_miles_wins_even_when_much_slower() -> None:
    ranked = rank([_route("FAST", severe=0.2, hours=2), _route("SLOW", hours=20)])
    assert _ids(ranked) == ["SLOW", "FAST"]


def test_fewest_severe_miles_beats_high_miles() -> None:
    a = _route("A", severe=10, high=0, hours=4)
    b = _route("B", severe=0, high=90, hours=9)
    assert _ids(rank([a, b])) == ["B", "A"]


def test_high_miles_break_a_severe_tie() -> None:
    ranked = rank([_route("A", severe=5, high=20), _route("B", severe=5, high=10)])
    assert _ids(ranked) == ["B", "A"]


def test_average_risk_breaks_a_severe_and_high_tie() -> None:
    ranked = rank([_route("A", high=10, avg=0.8), _route("B", high=10, avg=0.4)])
    assert _ids(ranked) == ["B", "A"]


def test_travel_time_breaks_a_full_risk_tie() -> None:
    ranked = rank([_route("A", avg=0.2, hours=6), _route("B", avg=0.2, hours=5)])
    assert _ids(ranked) == ["B", "A"]


def test_float_noise_counts_as_a_tie() -> None:
    a = _route("A", severe=10.0001, avg=0.30001, hours=5)
    b = _route("B", severe=10.0, avg=0.3, hours=6)
    assert _ids(rank([a, b])) == ["A", "B"]


def test_full_tie_keeps_provider_order_deterministically() -> None:
    assert _ids(rank([_route("A"), _route("B"), _route("C")])) == ["A", "B", "C"]
    assert _ids(rank([_route("C"), _route("A"), _route("B")])) == ["C", "A", "B"]


def test_provider_order_does_not_decide_the_winner() -> None:
    routes = [_route("A", severe=5, hours=4), _route("B", high=9, hours=6), _route("C", high=3)]
    for order in itertools.permutations(routes):
        assert _ids(recommend(order).order) == ["C", "B", "A"]


def test_no_travel_miles_are_not_a_ranking_criterion() -> None:
    # Within the No Travel group the plain assessment order applies, not No Travel miles.
    a = _route("A", nt=1, severe=30)
    b = _route("B", nt=200, severe=0)
    assert _ids(rank([a, b])) == ["B", "A"]


# --- No Travel and missing forecasts: an explicit constraint before ranking ------------


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        (_route("A"), Eligibility.ELIGIBLE),
        (_route("A", nt=0.1), Eligibility.NO_TRAVEL),
        (_route("A", unknown=3), Eligibility.INCOMPLETE_FORECAST),
        (_route("A", unknown=0.01), Eligibility.ELIGIBLE),  # float noise
        (_route("A", nt=1, unknown=5), Eligibility.NO_TRAVEL),  # known danger wins
    ],
)
def test_eligibility(route, expected) -> None:
    assert eligibility(route) == expected


def test_a_no_travel_route_is_never_recommended() -> None:
    # B is better on every assessment criterion but crosses one No Travel mile.
    rec = recommend([_route("A", severe=80, high=40, hours=12), _route("B", nt=1, hours=3)])
    assert rec.status is Status.RECOMMENDED and rec.route_id == "A"
    assert _ids(rec.order) == ["A", "B"]
    assert [e.route_id for e in rec.exclusions] == ["B"]
    assert "No Travel conditions on 1.0 mi (safety constraint)" in rec.exclusions[0].reason
    assert rec.reason == "Route A is the only eligible route."


def test_explanation_compares_eligible_routes_with_the_assessment_order() -> None:
    rec = recommend([_route("A", severe=18), _route("B", severe=0, high=30), _route("C", nt=5)])
    assert rec.route_id == "B"
    assert rec.reason == "Route B beats Route A on Severe miles (0.0 mi vs 18.0 mi)."
    assert [e.route_id for e in rec.exclusions] == ["C"]


def test_explanation_against_every_other_eligible_route() -> None:
    rec = recommend([_route("A", avg=0.14, hours=7.5), _route("B", hours=8), _route("C", hours=9)])
    assert rec.reason == (
        "Route B beats Route C on travel time (8h 00m vs 9h 00m) "
        "and Route A on average risk (0.00 vs 0.14)."
    )


def test_explain_full_tie() -> None:
    rec = recommend([_route("A"), _route("B")])
    assert rec.reason == (
        "Route A ties Route B on every criterion; keeping the routing provider's order."
    )


def test_unforecast_miles_are_never_treated_as_safe() -> None:
    # Regression (audit D1): A had 90 unscored miles and used to beat B's 10 Severe miles.
    rec = recommend([_route("A", unknown=90), _route("B", severe=10)])
    assert rec.route_id == "B" and rec.status is Status.RECOMMENDED
    assert "no forecast for 90.0 mi, so it can't be confirmed safe" in rec.exclusions[0].reason


def test_provisional_pick_when_no_route_has_a_complete_forecast() -> None:
    rec = recommend([_route("A", unknown=5, severe=10), _route("B", unknown=40), _route("C", nt=2)])
    assert rec.status is Status.PROVISIONAL and rec.route_id == "B"
    assert _ids(rec.order) == ["B", "A", "C"]
    assert "provisional pick" in rec.warnings[0]
    assert "40.0 mi have no forecast" in rec.warnings[0]
    assert [e.route_id for e in rec.exclusions] == ["C"]


def test_no_recommendation_when_every_route_has_no_travel() -> None:
    rec = recommend([_route("A", nt=1, hours=3), _route("B", nt=3, severe=0)])
    assert rec.status is Status.NONE and rec.route_id is None
    assert rec.reason == "No route is recommended: every route has No Travel conditions."
    assert "Consider delaying" in rec.warnings[0]
    assert len(rec.exclusions) == 2
    assert _ids(rec.order) == ["A", "B"]  # still listed, in assessment order


def test_eligible_routes_are_listed_first() -> None:
    rec = recommend([_route("A", nt=1), _route("B", unknown=9), _route("C", severe=50)])
    assert _ids(rec.order) == ["C", "B", "A"]
    assert rec.route_id == "C"


def test_single_route() -> None:
    rec = recommend([_route("A")])
    assert rec.route_id == "A" and rec.reason == "Route A is the only eligible route."
