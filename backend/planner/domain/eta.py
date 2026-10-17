"""Travel time as a function of distance along a route.

The routing API reports cumulative travel time at a few hundred points. Interpolating between
them keeps city stretches slow and interstate stretches fast, instead of assuming one average
speed for the whole trip.
"""

from bisect import bisect_right
from collections.abc import Iterable


class TimeProfile:
    def __init__(self, samples: Iterable[tuple[float, float]]):
        """`samples` are (distance, elapsed_seconds) pairs, in any distance unit."""
        distances: list[float] = []
        seconds: list[float] = []
        for d, s in sorted(samples):
            if distances and d <= distances[-1]:
                # Keep the curve a function of distance; the later time wins on ties.
                seconds[-1] = max(seconds[-1], s)
                continue
            distances.append(d)
            seconds.append(max(s, seconds[-1]) if seconds else s)
        if len(distances) < 2:
            raise ValueError("a time profile needs at least two distinct points")
        self._d = distances
        self._s = seconds

    @property
    def total_seconds(self) -> float:
        return self._s[-1]

    def seconds_at(self, distance: float) -> float:
        d, s = self._d, self._s
        if distance <= d[0]:
            return s[0]
        if distance >= d[-1]:
            return s[-1]
        i = bisect_right(d, distance) - 1
        t = (distance - d[i]) / (d[i + 1] - d[i])
        return s[i] + (s[i + 1] - s[i]) * t
