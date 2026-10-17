from django.http import HttpRequest, JsonResponse
from django.urls import include, path

urlpatterns = [
    path("api/", include("planner.urls")),
]


def json_not_found(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    """Unknown paths get the API's error shape instead of Django's HTML page."""
    return JsonResponse({"error": {"code": "not_found", "message": "Not found."}}, status=404)


def json_server_error(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": "server_error", "message": "Something went wrong."}}, status=500
    )


handler404 = json_not_found
handler500 = json_server_error
