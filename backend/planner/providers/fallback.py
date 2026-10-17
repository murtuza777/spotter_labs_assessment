"""Try several geocoders in order, skipping one for a while after it fails."""

import logging
import time
from collections.abc import Callable, Sequence

from planner.providers.base import Geocoder, Place, ProviderError

log = logging.getLogger(__name__)


class FallbackGeocoder:
    """The first healthy geocoder answers. A geocoder that fails is skipped for `cooldown_s`,
    so a provider that is unreachable from the host (e.g. one that blocks datacenter IPs)
    does not add its connect timeout to every keystroke."""

    def __init__(
        self,
        geocoders: Sequence[tuple[str, Geocoder]],
        *,
        cooldown_s: float = 600,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not geocoders:
            raise ValueError("at least one geocoder is required")
        self._geocoders = list(geocoders)
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._down_until: dict[str, float] = {}

    def search(self, query: str, limit: int = 6) -> list[Place]:
        now = self._clock()
        healthy = [(n, g) for n, g in self._geocoders if self._down_until.get(n, 0) <= now]
        # If everything is cooling down, try them all anyway rather than fail outright.
        candidates = healthy or self._geocoders
        last_error: ProviderError | None = None
        for name, geocoder in candidates:
            try:
                return geocoder.search(query, limit)
            except ProviderError as exc:
                log.warning(
                    "geocoder %s failed (%s); skipping it for %ds", name, exc.code, self._cooldown_s
                )
                self._down_until[name] = self._clock() + self._cooldown_s
                last_error = exc
        assert last_error is not None
        raise last_error
