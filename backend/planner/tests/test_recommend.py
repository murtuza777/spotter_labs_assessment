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
    assert explain(ranked) == "Route B: 0.0 Severe miles vs 18.0 Severe miles on Route A"


def test_explain_travel_time() -> None:
    ranked = rank([_route("A", hours=6.5), _route("B", hours=5.25)])
    assert explain(ranked) == "Route B: 5h 15m vs 6h 30m on Route A"


def test_explain_single_route() -> None:
    assert explain([_route("A")]) == "Route A is the only route available."


def test_warning_when_every_route_has_no_travel() -> None:
    assert len(warnings([_route("A", nt=1), _route("B", nt=3)])) == 1
    assert warnings([_route("A", nt=1), _route("B")]) == []


def test_warning_for_unknown_weather() -> None:
    assert any("unavailable" in w for w in warnings([_route("A", unknown=12)]))
