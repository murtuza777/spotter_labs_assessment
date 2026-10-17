"""Grid points covering the trip corridor, for the weather heatmap."""

import math
from collections.abc import Sequence

from planner.domain.geo import haversine_mi, resample
from planner.domain.models import LatLon

MILES_PER_DEG_LAT = 69.0


def corridor_grid(
    routes: Sequence[Sequence[LatLon]],
    *,
    buffer_mi: float = 60.0,
    base_step_deg: float = 0.25,
    max_points: int = 220,
) -> tuple[float, list[LatLon]]:
    """Regular lat/lon grid points within `buffer_mi` of any route.

    The step starts at `base_step_deg` (the weather model's grid) and doubles until the point
    count fits `max_points`, which keeps long trips inside the weather API budget. Points sit
    on multiples of the step, so they line up with snapped checkpoint cells and share cache.
    """
    samples = [p for route in routes for p in resample(route, step_mi=10.0)]
    if not samples:
        return base_step_deg, []

    lat_pad = buffer_mi / MILES_PER_DEG_LAT
    min_lat = min(p.lat for p in samples) - lat_pad
    max_lat = max(p.lat for p in samples) + lat_pad
    mid_lat = math.radians((min_lat + max_lat) / 2)
    lon_pad = buffer_mi / (MILES_PER_DEG_LAT * max(math.cos(mid_lat), 0.2))
    min_lon = min(p.lon for p in samples) - lon_pad
    max_lon = max(p.lon for p in samples) + lon_pad

    step = base_step_deg
    while True:
        points = _grid_within(samples, step, buffer_mi, (min_lat, max_lat, min_lon, max_lon))
        if len(points) <= max_points:
            return step, points
        step *= 2


def _grid_within(
    samples: Sequence[LatLon],
    step: float,
    buffer_mi: float,
    bbox: tuple[float, float, float, float],
) -> list[LatLon]:
    min_lat, max_lat, min_lon, max_lon = bbox
    # Bucket route samples by coarse cell so each grid point only checks nearby samples.
    bucket_deg = max(step, buffer_mi / MILES_PER_DEG_LAT)
    buckets: dict[tuple[int, int], list[LatLon]] = {}
    for p in samples:
        key = (math.floor(p.lat / bucket_deg), math.floor(p.lon / bucket_deg))
        buckets.setdefault(key, []).append(p)

    out: list[LatLon] = []
    lat = math.ceil(min_lat / step) * step
    while lat <= max_lat:
        lon = math.ceil(min_lon / step) * step
        while lon <= max_lon:
            cell = LatLon(round(lat, 6), round(lon, 6))
            bi, bj = math.floor(cell.lat / bucket_deg), math.floor(cell.lon / bucket_deg)
            near = (
                p
                for di in (-1, 0, 1)
                for dj in (-2, -1, 0, 1, 2)
                for p in buckets.get((bi + di, bj + dj), ())
            )
            if any(haversine_mi(cell, p) <= buffer_mi for p in near):
                out.append(cell)
            lon += step
        lat += step
    return out
