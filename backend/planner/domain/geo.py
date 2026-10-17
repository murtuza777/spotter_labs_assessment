"""Geometry on polylines of LatLon points. Distances are in miles unless noted."""

import math
from bisect import bisect_right
from collections.abc import Sequence

from planner.domain.models import LatLon

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def cumulative_miles(points: Sequence[LatLon]) -> list[float]:
    """Distance from the first point to each point along the polyline."""
    if not points:
        return []
    out = [0.0]
    for prev, cur in zip(points, points[1:], strict=False):
        out.append(out[-1] + haversine_mi(prev, cur))
    return out


def interpolate_along(points: Sequence[LatLon], cum: Sequence[float], mile: float) -> LatLon:
    """The point `mile` miles along the polyline (clamped to its ends)."""
    if mile <= 0:
        return points[0]
    if mile >= cum[-1]:
        return points[-1]
    i = bisect_right(cum, mile) - 1
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg == 0 else (mile - cum[i]) / seg
    a, b = points[i], points[i + 1]
    return LatLon(a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t)


def resample(points: Sequence[LatLon], step_mi: float) -> list[LatLon]:
    """Evenly spaced points every `step_mi` along the polyline, including both ends."""
    cum = cumulative_miles(points)
    total = cum[-1]
    count = max(1, math.ceil(total / step_mi))
    return [interpolate_along(points, cum, total * i / count) for i in range(count + 1)]


def simplify(points: Sequence[LatLon], tolerance_m: float) -> list[LatLon]:
    """Douglas-Peucker simplification on a local equirectangular projection."""
    if len(points) < 3:
        return list(points)
    lat0 = math.radians(sum(p.lat for p in points) / len(points))
    m_per_deg = math.pi * EARTH_RADIUS_MI * METERS_PER_MILE / 180
    xy = [(p.lon * m_per_deg * math.cos(lat0), p.lat * m_per_deg) for p in points]

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        (x1, y1), (x2, y2) = xy[start], xy[end]
        dx, dy = x2 - x1, y2 - y1
        seg_len_sq = dx * dx + dy * dy
        worst_i, worst_d = -1, tolerance_m
        for i in range(start + 1, end):
            px, py = xy[i]
            if seg_len_sq == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len_sq))
                d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
            if d > worst_d:
                worst_i, worst_d = i, d
        if worst_i != -1:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))
    return [p for p, k in zip(points, keep, strict=True) if k]


def encode_polyline(points: Sequence[LatLon], precision: int = 5) -> str:
    """Google encoded-polyline format (lat,lon order)."""
    factor = 10**precision
    out: list[str] = []
    prev_lat = prev_lon = 0
    for p in points:
        lat, lon = round(p.lat * factor), round(p.lon * factor)
        for delta in (lat - prev_lat, lon - prev_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lon = lat, lon
    return "".join(out)


def decode_polyline(encoded: str, precision: int = 5) -> list[LatLon]:
    factor = 10**precision
    coords: list[LatLon] = []
    index = lat = lon = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coords.append(LatLon(lat / factor, lon / factor))
    return coords


def snap(value: float, step: float) -> float:
    """Snap a coordinate to the nearest multiple of `step` (e.g. a model grid)."""
    return round(round(value / step) * step, 6)
