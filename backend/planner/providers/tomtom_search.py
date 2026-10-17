"""TomTom Search API (fuzzy search, typeahead) place autocomplete."""

import logging
from urllib.parse import quote

import httpx

from planner.providers.base import Place, ProviderError

log = logging.getLogger(__name__)

BASE_URL = "https://api.tomtom.com/search/2/search"


class TomTomGeocoder:
    def __init__(self, api_key: str, client: httpx.Client):
        self._key = api_key
        self._client = client

    def search(self, query: str, limit: int = 6) -> list[Place]:
        if not self._key:
            raise ProviderError(
                "geocoding_unavailable", "Place search is not configured.", status=503
            )
        params = {
            "key": self._key,
            "limit": str(limit),
            "typeahead": "true",
            "countrySet": "US,CA,MX",
            # Geographies, point addresses, address ranges and streets: places a trip starts at.
            "idxSet": "Geo,PAD,Addr,Str",
        }
        try:
            response = self._client.get(f"{BASE_URL}/{quote(query, safe='')}.json", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("TomTom search failed: %s", type(exc).__name__)
            raise ProviderError("geocoding_unavailable", "Place search is unavailable.") from exc

        places: list[Place] = []
        seen: set[str] = set()
        for result in response.json().get("results", []):
            place = _to_place(result)
            if place and place.label not in seen:
                seen.add(place.label)
                places.append(place)
        return places


def _to_place(result: dict) -> Place | None:
    address = result.get("address") or {}
    position = result.get("position") or {}
    label = address.get("freeformAddress")
    if not label or "lat" not in position or "lon" not in position:
        return None
    country = address.get("countryCode")
    if country and not label.endswith(country):
        label = f"{label}, {country}"
    return Place(label=label, lat=float(position["lat"]), lon=float(position["lon"]))
