"""TomTom Routing API (calculateRoute) in truck mode."""

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

from planner.domain.models import LatLon
from planner.providers.base import ProgressPoint, ProviderError, RouteOption

log = logging.getLogger(__name__)

BASE_URL = "https://api.tomtom.com/routing/1/calculateRoute"
TRANSIENT_RETRIES = 1
RETRY_BACKOFF_S = 0.5


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

        response = self._get_with_retry(f"{BASE_URL}/{locations}/json", params)
        if response.status_code != 200:
            raise _error_for(response, self._key)
        try:
            raw_routes = response.json().get("routes", [])
        except (ValueError, AttributeError) as exc:
            raise _malformed() from exc
        if not isinstance(raw_routes, list):
            raise _malformed()
        routes = [r for r in (parse_route(raw) for raw in raw_routes) if r is not None]
        if raw_routes and not routes:
            raise _malformed()
        return routes

    def _get_with_retry(self, url: str, params: list[tuple[str, str]]) -> httpx.Response:
        """One retry, only for transient failures (timeouts, connection errors, 5xx).

        429 is not retried: it means the quota is spent, and retrying would only burn more.
        """
        for attempt in range(TRANSIENT_RETRIES + 1):
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                log.warning(
                    "TomTom request failed (attempt %d): %s", attempt + 1, type(exc).__name__
                )
                if attempt == TRANSIENT_RETRIES:
                    raise ProviderError(
                        "routing_unavailable", "The routing service did not respond."
                    ) from exc
            else:
                if response.status_code < 500 or attempt == TRANSIENT_RETRIES:
                    return response
                log.warning("TomTom HTTP %s (attempt %d)", response.status_code, attempt + 1)
            time.sleep(RETRY_BACKOFF_S)
        raise AssertionError("unreachable")


def _depart_param(depart_at: datetime) -> str:
    # TomTom rejects departure times in the past; anything up to a minute ahead is "now".
    if depart_at <= datetime.now(UTC) + timedelta(minutes=1):
        return "now"
    return depart_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _malformed() -> ProviderError:
    return ProviderError(
        "routing_unavailable", "The routing service returned an unexpected response."
    )


def _error_for(response: httpx.Response, api_key: str = "") -> ProviderError:
    detail = ""
    try:
        body = response.json()
        detail = str((body.get("detailedError") or body.get("error") or {}).get("message", ""))
    except (ValueError, AttributeError):
        pass
    # The message is shown to users: never echo the key, and keep it short.
    if api_key:
        detail = detail.replace(api_key, "***")
    detail = detail[:200]
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


def parse_route(data: object) -> RouteOption | None:
    """One TomTom route, or None if it is malformed (logged, never raised).

    Legs are concatenated: TomTom's `progress` point indices run across the whole route, not
    per leg (verified against a live waypoint route), so they index the joined polyline.
    """
    try:
        points = [
            LatLon(float(p["latitude"]), float(p["longitude"]))
            for leg in data["legs"]
            for p in leg["points"]
        ]
        summary = data["summary"]
        length_m = float(summary["lengthInMeters"])
        duration_s = float(summary["travelTimeInSeconds"])
        progress = [
            ProgressPoint(
                point_index=int(p["pointIndex"]),
                distance_m=float(p.get("distanceInMeters", 0)),
                travel_time_s=float(p.get("travelTimeInSeconds", 0)),
            )
            for p in data.get("progress", [])
            if isinstance(p, dict) and "pointIndex" in p
        ]
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("Skipping malformed TomTom route: %s", type(exc).__name__)
        return None
    valid_points = all(-90 <= p.lat <= 90 and -180 <= p.lon <= 180 for p in points)
    if len(points) < 2 or length_m <= 0 or duration_s <= 0 or not valid_points:
        log.warning("Skipping TomTom route with no usable geometry or summary")
        return None
    progress = [p for p in progress if 0 <= p.point_index < len(points) and p.travel_time_s >= 0]
    return RouteOption(points=points, length_m=length_m, duration_s=duration_s, progress=progress)
