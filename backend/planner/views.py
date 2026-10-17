import hashlib
import logging

from django.core.cache import cache
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import exception_handler

from planner import deps
from planner.presenters import heatmap_json, plan_json
from planner.providers.base import ProviderError
from planner.serializers import (
    GeocodeQuerySerializer,
    HeatmapRequestSerializer,
    PlanRequestSerializer,
)

log = logging.getLogger(__name__)

GEOCODE_CACHE_S = 24 * 3600


class PlanThrottle(AnonRateThrottle):
    scope = "plan"


@api_view(["GET"])
@throttle_classes([])
def health(request: Request) -> Response:
    return Response({"status": "ok"})


@api_view(["GET"])
def geocode(request: Request) -> Response:
    query = GeocodeQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    q = query.validated_data["q"].strip()
    key = "geo:" + hashlib.sha1(" ".join(q.lower().split()).encode()).hexdigest()
    results = cache.get(key)
    if results is None:
        places = deps.geocoder().search(q)
        results = [{"label": p.label, "lat": p.lat, "lon": p.lon} for p in places]
        cache.set(key, results, GEOCODE_CACHE_S)
    return Response({"results": results})


@api_view(["POST"])
@throttle_classes([PlanThrottle])
def plan(request: Request) -> Response:
    payload = PlanRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    result = deps.trip_planner().plan(payload.to_request())
    return Response(plan_json(result))


@api_view(["POST"])
@throttle_classes([PlanThrottle])
def heatmap(request: Request) -> Response:
    payload = HeatmapRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    v = payload.validated_data
    result = deps.heatmap_builder().build(
        v["routes"], v["departure_time"], v["load_weight_lb"], v["wind_metric"]
    )
    return Response(heatmap_json(result))


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """One error shape for every failure: {"error": {"code", "message", "details"?}}."""
    if isinstance(exc, ProviderError):
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status)
    response = exception_handler(exc, context)
    if response is None:
        log.exception("Unhandled API error", exc_info=exc)
        return Response(
            {"error": {"code": "server_error", "message": "Something went wrong."}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if isinstance(exc, ValidationError):
        body = {"code": "invalid_request", "message": "Check the highlighted fields."}
        body["details"] = response.data
    elif isinstance(exc, APIException):
        body = {"code": exc.default_code, "message": str(exc.detail)}
    else:
        body = {"code": "error", "message": str(response.data)}
    response.data = {"error": body}
    return response
