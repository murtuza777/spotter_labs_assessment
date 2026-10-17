from datetime import UTC, datetime, timedelta

from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from planner.domain.geo import decode_polyline, haversine_mi
from planner.domain.models import LatLon
from planner.domain.risk import WIND_METRICS
from planner.domain.sampling import ALLOWED_INTERVALS_MI
from planner.providers.base import Place
from planner.services.plan_trip import TripRequest

MAX_LOAD_LB = 80_000
MAX_DEPARTURE_AHEAD = timedelta(days=7)
MAX_DEPARTURE_BEHIND = timedelta(hours=1)


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=200)
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)

    def to_place(self, data: dict) -> Place:
        return Place(label=data["label"], lat=data["lat"], lon=data["lon"])


TZ_REQUIRED = "Include a timezone offset, e.g. 2026-10-18T14:00:00Z."


class AwareDateTimeField(serializers.DateTimeField):
    """Rejects timestamps without a UTC offset instead of silently assuming UTC.

    A naive '2026-10-18T14:00' is ambiguous for a cross-country trip (it could be any of
    four US time zones), and guessing wrong shifts every checkpoint's forecast hour.
    """

    def to_internal_value(self, value: object) -> datetime:
        if isinstance(value, str):
            parsed = parse_datetime(value.strip())
            if parsed is not None and parsed.tzinfo is None:
                raise serializers.ValidationError(TZ_REQUIRED)
        return super().to_internal_value(value)


def _validate_departure(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise serializers.ValidationError(TZ_REQUIRED)
    now = datetime.now(UTC)
    if value < now - MAX_DEPARTURE_BEHIND:
        raise serializers.ValidationError("Departure can't be more than an hour in the past.")
    if value > now + MAX_DEPARTURE_AHEAD:
        raise serializers.ValidationError("Departure must be within the next 7 days.")
    return value


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure_time = AwareDateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    sample_interval_mi = serializers.ChoiceField(choices=ALLOWED_INTERVALS_MI)
    wind_metric = serializers.ChoiceField(choices=WIND_METRICS, default="gust")

    def validate_departure_time(self, value: datetime) -> datetime:
        return _validate_departure(value)

    def validate(self, attrs: dict) -> dict:
        o, d = attrs["origin"], attrs["destination"]
        if haversine_mi(LatLon(o["lat"], o["lon"]), LatLon(d["lat"], d["lon"])) < 1:
            raise serializers.ValidationError(
                {"destination": "Destination must be at least a mile from the origin."}
            )
        return attrs

    def to_request(self) -> TripRequest:
        v = self.validated_data
        return TripRequest(
            origin=PlaceSerializer().to_place(v["origin"]),
            destination=PlaceSerializer().to_place(v["destination"]),
            departure=v["departure_time"],
            load_lb=v["load_weight_lb"],
            interval_mi=int(v["sample_interval_mi"]),
            wind_metric=v["wind_metric"],
        )


class HeatmapRequestSerializer(serializers.Serializer):
    routes = serializers.ListField(
        child=serializers.CharField(max_length=200_000), min_length=1, max_length=3
    )
    departure_time = AwareDateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    wind_metric = serializers.ChoiceField(choices=WIND_METRICS, default="gust")

    def validate_departure_time(self, value: datetime) -> datetime:
        return _validate_departure(value)

    def validate_routes(self, value: list[str]) -> list[list[LatLon]]:
        try:
            decoded = [decode_polyline(r) for r in value]
        except (IndexError, ValueError) as exc:
            raise serializers.ValidationError("Routes must be encoded polylines.") from exc
        if any(len(r) < 2 for r in decoded):
            raise serializers.ValidationError("Each route needs at least two points.")
        return decoded


class GeocodeQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=120)
