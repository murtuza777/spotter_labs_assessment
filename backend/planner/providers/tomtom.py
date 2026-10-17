"""TomTom Routing API (calculateRoute) in truck mode."""

import logging
from datetime import UTC, datetime, timedelta

import httpx

from planner.domain.models import LatLon
from planner.providers.base import ProgressPoint, ProviderError, RouteOption

log = logging.getLogger(__name__)

BASE_URL = "https://api.tomtom.com/routing/1/calculateRoute"


class TomTomRouting:
    def __init__(self, api_key: str, client: httpx.Client):
        self._key = api_key
        self._client = client

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
        if not self._key:
            raise ProviderError("routing_not_configured", "TomTom API key is not set.", status=503)
        stops = [origin, *([via] if via else []), destination]
        locations = ":".join(f"{p.lat:.6f},{p.lon:.6f}" for p in stops)
        params: list[tuple[str, str]] = [
            ("key", self._key),
            ("travelMode", "truck"),
            ("vehicleCommercial", "true"),
            ("vehicleWeight", str(vehicle_weight_kg)),
            ("traffic", "true"),
            ("departAt", _depart_param(depart_at)),
            ("routeRepresentation", "polyline"),
            ("extendedRouteRepresentation", "distance"),
            ("extendedRouteRepresentation", "travelTime"),
        ]
        if max_alternatives:
            params += [("maxAlternatives", str(max_alternatives)), ("alternativeType", "anyRoute")]

        try:
            response = self._client.get(f"{BASE_URL}/{locations}/json", params=params)
        except httpx.HTTPError as exc:
            log.warning("TomTom request failed: %s", type(exc).__name__)
            raise ProviderError(
                "routing_unavailable", "The routing service did not respond."
            ) from exc

        if response.status_code != 200:
            raise _error_for(response)
        return [parse_route(r) for r in response.json().get("routes", [])]


def _depart_param(depart_at: datetime) -> str:
    # TomTom rejects departure times in the past; anything up to a minute ahead is "now".
    if depart_at <= datetime.now(UTC) + timedelta(minutes=1):
        return "now"
    return depart_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _error_for(response: httpx.Response) -> ProviderError:
    detail = ""
    try:
        body = response.json()
        detail = (body.get("detailedError") or body.get("error") or {}).get("message", "")
    except ValueError:
        pass
    log.warning("TomTom HTTP %s: %s", response.status_code, detail)
    if response.status_code in (400, 404) and detail:
        lowered = detail.lower().replace("_", " ")
        if "no route" in lowered or "cannot find" in lowered:
            return ProviderError(
                "no_route", "No truck route was found between those places.", status=422
            )
        return ProviderError("routing_rejected", f"Routing request rejected: {detail}", status=422)
    if response.status_code in (401, 403):
        return ProviderError("routing_not_configured", "TomTom rejected the API key.", status=503)
    if response.status_code == 429:
        return ProviderError(
            "routing_rate_limited", "Routing quota exceeded; try again shortly.", status=503
        )
    return ProviderError("routing_unavailable", "The routing service returned an error.")


def parse_route(data: dict) -> RouteOption:
    points = [
        LatLon(p["latitude"], p["longitude"]) for leg in data.get("legs", []) for p in leg["points"]
    ]
    summary = data["summary"]
    progress = [
        ProgressPoint(
            point_index=p["pointIndex"],
            distance_m=float(p.get("distanceInMeters", 0)),
            travel_time_s=float(p.get("travelTimeInSeconds", 0)),
        )
        for p in data.get("progress", [])
        if "pointIndex" in p
    ]
    return RouteOption(
        points=points,
        length_m=float(summary["lengthInMeters"]),
        duration_s=float(summary["travelTimeInSeconds"]),
        progress=progress,
    )
