from planner.domain.models import RiskLevel as L
from planner.domain.models import RouteSummary, ScoredRoute
from planner.domain.recommend import explain, rank, warnings


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


def _ids(routes: list[ScoredRoute]) -> list[str]:
    return [r.id for r in routes]


def test_no_travel_miles_rank_before_severe_miles() -> None:
    a = _route("A", nt=5)
    b = _route("B", severe=50)
    assert _ids(rank([a, b])) == ["B", "A"]


def test_fewest_severe_miles_wins_first() -> None:
    a = _route("A", severe=10, high=0, hours=4)
    b = _route("B", severe=0, high=90, hours=9)
    assert _ids(rank([a, b])) == ["B", "A"]


def test_high_miles_break_severe_tie() -> None:
    a = _route("A", severe=5, high=20)
    b = _route("B", severe=5, high=10)
    assert _ids(rank([a, b])) == ["B", "A"]


def test_average_risk_breaks_high_tie() -> None:
    a = _route("A", high=10, avg=0.8)
    b = _route("B", high=10, avg=0.4)
    assert _ids(rank([a, b])) == ["B", "A"]


def test_travel_time_breaks_full_risk_tie() -> None:
    a = _route("A", avg=0.2, hours=6)
    b = _route("B", avg=0.2, hours=5)
    assert _ids(rank([a, b])) == ["B", "A"]


def test_float_noise_counts_as_a_tie() -> None:
    a = _route("A", severe=10.0001, avg=0.30001, hours=5)
    b = _route("B", severe=10.0, avg=0.3, hours=6)
    assert _ids(rank([a, b])) == ["A", "B"]


def test_explain_names_first_deciding_criterion() -> None:
    ranked = rank([_route("A", severe=18), _route("B", severe=0, high=30)])
    assert explain(ranked) == "Route B beats Route A on Severe miles (0.0 mi vs 18.0 mi)."


def test_explain_travel_time() -> None:
    ranked = rank([_route("A", hours=6.5), _route("B", hours=5.25)])
    assert explain(ranked) == "Route B beats Route A on travel time (5h 15m vs 6h 30m)."


def test_explain_covers_every_other_route() -> None:
    ranked = rank([_route("A", avg=0.14, hours=7.5), _route("B", hours=8), _route("C", hours=9)])
    assert explain(ranked) == (
        "Route B beats Route C on travel time (8h 00m vs 9h 00m) "
        "and Route A on average risk (0.00 vs 0.14)."
    )


def test_explain_full_tie() -> None:
    ranked = rank([_route("A"), _route("B")])
    assert explain(ranked) == (
        "Route A ties Route B on every criterion; keeping the routing API's first choice."
    )


def test_explain_single_route() -> None:
    assert explain([_route("A")]) == "Route A is the only route available."


def test_warning_when_every_route_has_no_travel() -> None:
    ranked = rank([_route("A", nt=1), _route("B", nt=3)])
    [msg] = warnings(ranked)
    assert "Every route has No Travel" in msg and "Route A" in msg
    assert warnings(rank([_route("A", nt=1), _route("B")])) == []


def test_no_travel_route_never_recommended_over_one_without() -> None:
    # B is faster, has no Severe or High miles, but crosses one No Travel mile.
    ranked = rank([_route("A", severe=80, high=40, hours=12), _route("B", nt=1, hours=3)])
    assert [r.id for r in ranked] == ["A", "B"]
    assert warnings(ranked) == []
    assert "No Travel miles" in explain(ranked)


def test_unforecast_miles_are_never_treated_as_safe() -> None:
    # Regression (audit D1): A had 90 unscored miles and used to beat B's 10 Severe miles.
    ranked = rank([_route("A", unknown=90), _route("B", severe=10)])
    assert [r.id for r in ranked] == ["B", "A"]
    assert explain(ranked) == (
        "Route B beats Route A on forecast coverage (complete vs 90.0 mi unforecast)."
    )
    assert "ranked after fully forecast ones" in warnings(ranked)[0]


def test_coverage_gate_does_not_override_no_travel() -> None:
    ranked = rank([_route("A", unknown=20), _route("B", nt=2)])
    assert [r.id for r in ranked] == ["A", "B"]
    assert "No forecast was available for 20.0 mi of Route A" in warnings(ranked)[0]


def test_two_partially_forecast_routes_fall_back_to_the_brief_order() -> None:
    ranked = rank([_route("A", unknown=5, severe=10), _route("B", unknown=40, severe=0)])
    assert [r.id for r in ranked] == ["B", "A"]


def test_tiny_unknown_stretch_is_float_noise() -> None:
    ranked = rank([_route("A", unknown=0.01, hours=4), _route("B", hours=5)])
    assert [r.id for r in ranked] == ["A", "B"]


def test_api_order_does_not_decide_the_winner() -> None:
    import itertools

    routes = [_route("A", severe=5, hours=4), _route("B", high=9, hours=6), _route("C", high=3)]
    for order in itertools.permutations(routes):
        assert [r.id for r in rank(order)] == ["C", "B", "A"]


def test_longer_route_with_fewer_severe_miles_wins() -> None:
    ranked = rank([_route("FAST", severe=0.2, hours=2), _route("SLOW", severe=0.0, hours=20)])
    assert ranked[0].id == "SLOW"
