"""Photon (komoot, OpenStreetMap data) place autocomplete."""

import logging

import httpx

from planner.providers.base import Place, ProviderError

log = logging.getLogger(__name__)

# Contiguous US, Canada, Alaska and Mexico: where truck routing and miles make sense.
NORTH_AMERICA_BBOX = "-170,14,-50,72"


class PhotonGeocoder:
    def __init__(self, client: httpx.Client, *, base_url: str):
        self._client = client
        self._base_url = base_url

    def search(self, query: str, limit: int = 6) -> list[Place]:
        params = {"q": query, "limit": str(limit * 2), "lang": "en", "bbox": NORTH_AMERICA_BBOX}
        try:
            response = self._client.get(self._base_url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Photon request failed: %s", type(exc).__name__)
            raise ProviderError("geocoding_unavailable", "Place search is unavailable.") from exc

        places: list[Place] = []
        seen: set[str] = set()
        for feature in response.json().get("features", []):
            place = _to_place(feature)
            if place and place.label not in seen:
                seen.add(place.label)
                places.append(place)
            if len(places) == limit:
                break
        return places


def _to_place(feature: dict) -> Place | None:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) != 2:
        return None
    name = props.get("name")
    parts = [name, props.get("city"), props.get("state"), props.get("countrycode")]
    label_parts: list[str] = []
    for part in parts:
        if part and part not in label_parts:
            label_parts.append(part)
    if not label_parts:
        return None
    return Place(label=", ".join(label_parts), lat=float(coords[1]), lon=float(coords[0]))
