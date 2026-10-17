"""Where checkpoints go along a route."""

ALLOWED_INTERVALS_MI = (10, 25, 50)
_END_EPSILON_MI = 0.05


def checkpoint_miles(route_length_mi: float, interval_mi: float) -> list[float]:
    """0, N, 2N, ... along the route, plus the destination itself.

    The destination is always included so the end of the trip is assessed too; it is not
    duplicated when the route length is (almost) an exact multiple of the interval.
    """
    if interval_mi <= 0:
        raise ValueError("interval must be positive")
    if route_length_mi <= 0:
        return [0.0]
    miles: list[float] = []
    d = 0.0
    while d < route_length_mi - _END_EPSILON_MI:
        miles.append(d)
        d += interval_mi
    miles.append(route_length_mi)
    return miles
