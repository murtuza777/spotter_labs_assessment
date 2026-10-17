"""A short-lived cache in front of the routing provider.

TomTom is the slowest call in a plan (2.6-9.5 s measured), and resubmitting the same trip,
or a second reviewer trying the same demo, should not pay for it again. The key is the exact
request: endpoints, waypoint, departure minute, weight and alternatives. A different
departure time is a different key, because TomTom plans with traffic for that time. The TTL
is short (10 min by default) so live traffic for "now" departures doesn't go stale.
"""

import hashlib
from datetime import UTC, datetime

from django.core.cache import BaseCache

from planner.domain.models import LatLon
from planner.providers.base import RouteOption, RoutingProvider


class CachedRouting:
    def __init__(self, provider: RoutingProvider, cache: BaseCache, *, ttl_s: int):
        self._provider = provider
        self._cache = cache
        self._ttl = ttl_s
        self.hits = 0  # for tests and logging; approximate under concurrency
        self.misses = 0

    def routes(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        depart_at: datetime,
        vehicle_weight_kg: int,
        max_alternatives: int = 0,
        via: LatLon | None = None,
    ) -> list[RouteOption]:
        key = _key(origin, destination, depart_at, vehicle_weight_kg, max_alternatives, via)
        cached = self._cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        result = self._provider.routes(
            origin,
            destination,
            depart_at=depart_at,
            vehicle_weight_kg=vehicle_weight_kg,
            max_alternatives=max_alternatives,
            via=via,
        )
        if result:  # never cache failures or empty answers
            self._cache.set(key, result, timeout=self._ttl)
        return result


def _key(
    origin: LatLon,
    destination: LatLon,
    depart_at: datetime,
    weight_kg: int,
    alternatives: int,
    via: LatLon | None,
) -> str:
    parts = [
        f"{origin.lat:.5f},{origin.lon:.5f}",
        f"{destination.lat:.5f},{destination.lon:.5f}",
        f"{via.lat:.5f},{via.lon:.5f}" if via else "-",
        depart_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"),
        str(weight_kg),
        str(alternatives),
    ]
    return "route:" + hashlib.sha1("|".join(parts).encode()).hexdigest()
