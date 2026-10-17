from datetime import UTC, datetime, timedelta, timezone

import pytest

from planner.domain.corridor import corridor_grid
from planner.domain.eta import TimeProfile
from planner.domain.geo import (
    cumulative_miles,
    decode_polyline,
    encode_polyline,
    haversine_mi,
    interpolate_along,
    resample,
    simplify,
    snap,
)
from planner.domain.models import LatLon
from planner.domain.models import RiskLevel as L
from planner.domain.sampling import checkpoint_miles
from planner.domain.scoring import owned_miles, summarize
from planner.domain.timebucket import forecast_hour_for

# Along the equator one degree of longitude is ~69.17 miles.
EQ = [LatLon(0, 0), LatLon(0, 1), LatLon(0, 2)]
MI_PER_DEG_EQ = haversine_mi(LatLon(0, 0), LatLon(0, 1))


def test_haversine_known_distance() -> None:
    # Denver -> Salt Lake City is about 371 miles as the crow flies.
    d = haversine_mi(LatLon(39.7392, -104.9903), LatLon(40.7608, -111.8910))
    assert d == pytest.approx(371, abs=3)


def test_cumulative_and_interpolate() -> None:
    cum = cumulative_miles(EQ)
    assert cum[-1] == pytest.approx(2 * MI_PER_DEG_EQ)
    mid = interpolate_along(EQ, cum, MI_PER_DEG_EQ * 1.5)
    assert mid.lon == pytest.approx(1.5)
    assert interpolate_along(EQ, cum, -5) == EQ[0]
    assert interpolate_along(EQ, cum, 1e9) == EQ[-1]


def test_resample_includes_ends() -> None:
    pts = resample(EQ, step_mi=10)
    assert pts[0] == EQ[0]
    assert pts[-1].lon == pytest.approx(2)
    gaps = [haversine_mi(a, b) for a, b in zip(pts, pts[1:], strict=False)]
    assert max(gaps) <= 10 + 1e-6


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_checkpoints_every_interval_plus_destination(interval: int) -> None:
    miles = checkpoint_miles(137.0, interval)
    assert miles[0] == 0
    assert miles[-1] == 137.0
    assert all(
        b - a == pytest.approx(interval) for a, b in zip(miles[:-2], miles[1:-1], strict=False)
    )
    assert 0 < miles[-1] - miles[-2] <= interval


def test_checkpoints_no_duplicate_destination_on_exact_multiple() -> None:
    assert checkpoint_miles(50.0, 25) == [0.0, 25.0, 50.0]


def test_checkpoints_route_shorter_than_interval() -> None:
    assert checkpoint_miles(7.0, 50) == [0.0, 7.0]


def test_checkpoints_reject_bad_interval() -> None:
    with pytest.raises(ValueError):
        checkpoint_miles(100, 0)


def test_time_profile_interpolates_variable_speed() -> None:
    # 10 miles of city at 20 mph (30 min), then 60 miles of interstate at 60 mph (60 min).
    profile = TimeProfile([(0, 0), (10, 1800), (70, 5400)])
    assert profile.seconds_at(5) == pytest.approx(900)
    assert profile.seconds_at(40) == pytest.approx(1800 + 1800)
    assert profile.seconds_at(70) == profile.total_seconds == 5400
    assert profile.seconds_at(500) == 5400


def test_time_profile_ignores_non_increasing_points() -> None:
    profile = TimeProfile([(0, 0), (10, 600), (10, 650), (5, 300), (20, 1200)])
    assert profile.seconds_at(10) == 650
    assert profile.seconds_at(20) == 1200


def test_time_profile_needs_two_points() -> None:
    with pytest.raises(ValueError):
        TimeProfile([(0, 0)])


@pytest.mark.parametrize(
    ("minute", "second", "expected_hour"),
    [(0, 0, 14), (0, 1, 15), (20, 0, 15), (59, 59, 15)],
)
def test_forecast_hour_rounds_up(minute: int, second: int, expected_hour: int) -> None:
    eta = datetime(2026, 10, 18, 14, minute, second, tzinfo=UTC)
    assert forecast_hour_for(eta) == datetime(2026, 10, 18, expected_hour, tzinfo=UTC)


def test_forecast_hour_converts_to_utc_and_crosses_midnight() -> None:
    mdt = timezone(timedelta(hours=-6))
    eta = datetime(2026, 10, 18, 18, 30, tzinfo=mdt)  # 00:30 UTC next day
    assert forecast_hour_for(eta) == datetime(2026, 10, 19, 1, tzinfo=UTC)


def test_forecast_hour_requires_timezone() -> None:
    with pytest.raises(ValueError):
        forecast_hour_for(datetime(2026, 10, 18, 14))


def test_owned_miles_sum_to_route_length() -> None:
    miles = checkpoint_miles(137.0, 25)
    shares = owned_miles(miles, 137.0)
    assert sum(shares) == pytest.approx(137.0)
    assert shares[0] == pytest.approx(12.5)  # first owns half the gap to the next
    assert shares[1] == pytest.approx(25.0)
    assert shares[-1] == pytest.approx((137 - 125) / 2)


def test_owned_miles_edge_cases() -> None:
    assert owned_miles([], 10) == []
    assert owned_miles([0.0], 10) == [10]


def test_summarize_miles_avg_and_unknown() -> None:
    levels = [L.LOW, L.SEVERE, None, L.HIGH]
    shares = [10.0, 20.0, 5.0, 10.0]
    s = summarize(levels, shares)
    assert s.severe_miles == 20 and s.high_miles == 10 and s.no_travel_miles == 0
    assert s.unknown_miles == 5
    assert s.avg_risk == pytest.approx((0 * 10 + 3 * 20 + 2 * 10) / 40)
    assert s.max_level == L.SEVERE


def test_summarize_all_unknown() -> None:
    s = summarize([None, None], [5.0, 5.0])
    assert s.avg_risk == 0 and s.max_level is None and s.unknown_miles == 10


def test_polyline_round_trip_and_known_value() -> None:
    # Example from Google's polyline documentation.
    pts = [LatLon(38.5, -120.2), LatLon(40.7, -120.95), LatLon(43.252, -126.453)]
    assert encode_polyline(pts) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    decoded = decode_polyline(encode_polyline(pts))
    assert [(p.lat, p.lon) for p in decoded] == [(p.lat, p.lon) for p in pts]


def test_simplify_drops_collinear_points_keeps_corners() -> None:
    line = [LatLon(0, i / 100) for i in range(101)] + [LatLon(1, 1)]
    out = simplify(line, tolerance_m=30)
    assert out == [LatLon(0, 0), LatLon(0, 1), LatLon(1, 1)]


def test_snap_to_grid() -> None:
    assert snap(39.7392, 0.25) == 39.75
    assert snap(-104.9903, 0.25) == -105.0
    assert snap(-0.12, 0.25) == 0.0


def test_corridor_grid_covers_route_and_respects_cap() -> None:
    route = [LatLon(39.74, -104.99), LatLon(40.76, -111.89)]
    step, points = corridor_grid([route], buffer_mi=40, max_points=500)
    assert step == 0.25
    assert points
    assert all(
        round(p.lat / step, 6).is_integer() and round(p.lon / step, 6).is_integer() for p in points
    )
    samples = resample(route, 10)
    assert all(min(haversine_mi(p, s) for s in samples) <= 40 for p in points)

    capped_step, capped = corridor_grid([route], buffer_mi=40, max_points=60)
    assert len(capped) <= 60
    assert capped_step > step
