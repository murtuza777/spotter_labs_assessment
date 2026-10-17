from rest_framework.decorators import api_view, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
@throttle_classes([])
def health(request: Request) -> Response:
    return Response({"status": "ok"})
