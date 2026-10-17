from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from planner.domain.models import LatLon
from planner.providers.base import ProviderError
from planner.providers.openmeteo import OpenMeteoWeather, parse_response
from planner.providers.photon import PhotonGeocoder
from planner.providers.tomtom import BASE_URL, TomTomRouting, parse_route
from planner.tests.conftest import load_fixture

DEN = LatLon(39.7392, -104.9903)
SLC = LatLon(40.7608, -111.8910)
OM_URL = "https://api.open-meteo.com/v1/forecast"


def test_parse_tomtom_fixture(tomtom_routes) -> None:
    assert len(tomtom_routes) == 3
    first = tomtom_routes[0]
    assert first.length_m == 860878
    assert first.duration_s == 27278
    assert first.progress[0].travel_time_s == 0
    assert first.progress[-1].travel_time_s == pytest.approx(first.duration_s)
    assert first.progress[-1].point_index == len(first.points) - 1


@respx.mock
def test_tomtom_request_params_and_parse() -> None:
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("tomtom_denver_slc.json"))
    )
    client = TomTomRouting("k", httpx.Client())
    later = datetime.now(UTC) + timedelta(hours=5)
    out = client.routes(DEN, SLC, depart_at=later, vehicle_weight_kg=30000, max_alternatives=2)
    assert len(out) == 3
    params = route.calls.last.request.url.params
    assert params["travelMode"] == "truck"
    assert params["vehicleWeight"] == "30000"
    assert params["maxAlternatives"] == "2"
    assert params["departAt"].endswith("+00:00")
    assert params.get_list("extendedRouteRepresentation") == ["distance", "travelTime"]


@respx.mock
def test_tomtom_past_departure_becomes_now() -> None:
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"routes": []})
    )
    TomTomRouting("k", httpx.Client()).routes(
        DEN, SLC, depart_at=datetime.now(UTC) - timedelta(minutes=10), vehicle_weight_kg=1
    )
    assert route.calls.last.request.url.params["departAt"] == "now"


@respx.mock
@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (403, {"detailedError": {"message": "Forbidden"}}, "routing_not_configured"),
        (400, {"detailedError": {"message": "Engine error: NO_ROUTE_FOUND"}}, "no_route"),
        (400, {"detailedError": {"message": "Cannot find a route"}}, "no_route"),
        (400, {"detailedError": {"message": "Invalid departAt"}}, "routing_rejected"),
        (429, {}, "routing_rate_limited"),
        (500, {}, "routing_unavailable"),
    ],
)
def test_tomtom_errors(status, body, code) -> None:
    respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(ProviderError) as err:
        TomTomRouting("k", httpx.Client()).routes(
            DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
        )
    assert err.value.code == code


def test_tomtom_without_key_is_reported() -> None:
    with pytest.raises(ProviderError) as err:
        TomTomRouting("", httpx.Client()).routes(
            DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
        )
    assert err.value.status == 503


def test_parse_open_meteo_fixture() -> None:
    data = load_fixture("openmeteo_3_locations.json")
    cells = [LatLon(1, 1), LatLon(2, 2), LatLon(3, 3)]
    series = parse_response(data, cells)
    assert set(series) == set(cells)
    s = series[cells[0]]
    assert s.start.tzinfo is not None
    # rain = rain + showers
    raw = data[0]["hourly"]
    assert s.rain_in_hr[0] == pytest.approx(raw["rain"][0] + raw["showers"][0])
    assert s.gust_mph[0] == raw["wind_gusts_10m"][0]
    sample = s.at(s.start + timedelta(hours=3))
    assert sample is not None and sample.snow_in_hr == raw["snowfall"][3]
    assert s.at(s.start - timedelta(hours=1)) is None


def test_parse_open_meteo_single_location_object() -> None:
    one = load_fixture("openmeteo_3_locations.json")[0]
    assert len(parse_response(one, [LatLon(1, 1)])) == 1


def _om_body(n: int, start: datetime) -> list[dict]:
    t0 = int(start.timestamp())
    hourly = {
        "time": [t0, t0 + 3600],
        "wind_speed_10m": [5, 6],
        "wind_gusts_10m": [10, 11],
        "rain": [0, 0.1],
        "showers": [0, 0.05],
        "snowfall": [0, 0],
    }
    return [{"hourly": hourly} for _ in range(n)]


@respx.mock
def test_open_meteo_batches_and_retries() -> None:
    start = datetime(2026, 10, 18, tzinfo=UTC)
    route = respx.get(OM_URL).mock(
        side_effect=[
            httpx.Response(503, json={"error": True, "reason": "The service is overloaded"}),
            httpx.Response(200, json=_om_body(2, start)),
            httpx.Response(200, json=_om_body(1, start)),
        ]
    )
    weather = OpenMeteoWeather(
        httpx.Client(), base_url=OM_URL, batch_size=2, max_workers=1, backoff_s=0
    )
    cells = [LatLon(1, 1), LatLon(2, 2), LatLon(3, 3)]
    out = weather.hourly(cells, start, start + timedelta(hours=1))
    assert set(out) == set(cells)
    assert route.call_count == 3
    params = route.calls[0].request.url.params
    assert params["models"] == "gfs_seamless"
    assert params["precipitation_unit"] == "inch"
    assert params["start_hour"] == "2026-10-18T00:00"


@respx.mock
def test_open_meteo_gives_up_without_raising() -> None:
    respx.get(OM_URL).mock(return_value=httpx.Response(503, json={}))
    weather = OpenMeteoWeather(httpx.Client(), base_url=OM_URL, retries=1, backoff_s=0)
    start = datetime(2026, 10, 18, tzinfo=UTC)
    assert weather.hourly([LatLon(1, 1)], start, start) == {}


@respx.mock
def test_photon_labels_and_dedupes() -> None:
    feature = {
        "geometry": {"coordinates": [-104.99, 39.74]},
        "properties": {"name": "Denver", "state": "Colorado", "countrycode": "US"},
    }
    respx.get("https://photon.test/api").mock(
        return_value=httpx.Response(200, json={"features": [feature, feature]})
    )
    places = PhotonGeocoder(httpx.Client(), base_url="https://photon.test/api").search("denv")
    assert len(places) == 1
    assert places[0].label == "Denver, Colorado, US"
    assert (places[0].lat, places[0].lon) == (39.74, -104.99)


@respx.mock
def test_photon_failure_is_provider_error() -> None:
    respx.get("https://photon.test/api").mock(return_value=httpx.Response(500))
    with pytest.raises(ProviderError):
        PhotonGeocoder(httpx.Client(), base_url="https://photon.test/api").search("x")


def _hourly(**overrides):
    hourly = {
        "time": [0, 3600, 7200],
        "wind_speed_10m": [5, 6, 7],
        "wind_gusts_10m": [10, 11, 12],
        "rain": [0.0, 0.1, 0.2],
        "showers": [0.0, 0.0, 0.05],
        "snowfall": [0, 0, 0],
    }
    hourly.update(overrides)
    return {"hourly": hourly}


@pytest.mark.parametrize(
    ("overrides", "unknown_hours"),
    [
        ({"wind_gusts_10m": [10, None, 12]}, [1]),  # null reading
        ({"wind_gusts_10m": [10, "x", 12]}, [1]),  # string
        ({"snowfall": [0, -0.5, 0]}, [1]),  # negative
        ({"rain": [0.0, float("nan"), 0.2]}, [1]),  # NaN
        ({"wind_gusts_10m": [10]}, [1, 2]),  # series shorter than the time axis
        ({"rain": None}, [0, 1, 2]),  # rain missing: total liquid precip is unknown
        ({"showers": [0, 0, True]}, [2]),  # booleans aren't numbers here
    ],
)
def test_open_meteo_invalid_readings_become_unknown(overrides, unknown_hours) -> None:
    # Regression (audit D5): these used to slip through and crash or mis-score later.
    cell = LatLon(1, 1)
    series = parse_response(_hourly(**overrides), [cell])[cell]
    for h in range(3):
        sample = series.at(series.start + timedelta(hours=h))
        assert (sample is None) == (h in unknown_hours), h


@pytest.mark.parametrize(
    "payload",
    [
        "oops",
        42,
        None,
        [None],
        [{"hourly": "x"}],
        [{"hourly": {"time": [0, 1800]}}],
        [{"hourly": {"time": []}}],
    ],
)
def test_open_meteo_malformed_payloads_are_dropped(payload) -> None:
    assert parse_response(payload, [LatLon(1, 1)]) == {}


def test_open_meteo_rain_plus_showers_and_end_of_coverage() -> None:
    cell = LatLon(1, 1)
    series = parse_response(_hourly(), [cell])[cell]
    assert series.at(series.start + timedelta(hours=2)).rain_in_hr == pytest.approx(0.25)
    assert series.at(series.start + timedelta(hours=3)) is None  # beyond fetched coverage


@pytest.mark.parametrize(
    "route",
    [
        {"legs": [{"points": []}]},  # no summary
        {
            "legs": [{"points": [{"lon": 1}]}],
            "summary": {"lengthInMeters": 1, "travelTimeInSeconds": 1},
        },
        {"legs": "x", "summary": {}},
        {"summary": {"lengthInMeters": 1000, "travelTimeInSeconds": 60}},  # no legs
        {
            "legs": [{"points": [{"latitude": 1, "longitude": 1}]}],  # a single point
            "summary": {"lengthInMeters": 1000, "travelTimeInSeconds": 60},
        },
        {
            "legs": [
                {"points": [{"latitude": 1, "longitude": 1}, {"latitude": 1, "longitude": 2}]}
            ],
            "summary": {"lengthInMeters": 0, "travelTimeInSeconds": 60},  # zero length
        },
        {
            "legs": [
                {"points": [{"latitude": 95, "longitude": 1}, {"latitude": 1, "longitude": 2}]}
            ],
            "summary": {"lengthInMeters": 1000, "travelTimeInSeconds": 60},  # impossible latitude
        },
        "not a dict",
    ],
)
def test_parse_route_rejects_malformed_routes(route) -> None:
    # Regression (audit D4): these raised KeyError, which surfaced as a 500.
    assert parse_route(route) is None


def test_parse_route_drops_out_of_range_progress(tomtom_routes) -> None:
    raw = load_fixture("tomtom_denver_slc.json")["routes"][0]
    raw["progress"].append({"pointIndex": 10**6, "travelTimeInSeconds": 1, "distanceInMeters": 1})
    route = parse_route(raw)
    assert route is not None
    assert all(p.point_index < len(route.points) for p in route.progress)


@respx.mock
def test_tomtom_all_routes_malformed_is_a_502() -> None:
    respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"routes": [{"legs": []}, {"oops": 1}]})
    )
    with pytest.raises(ProviderError) as err:
        TomTomRouting("k", httpx.Client()).routes(
            DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
        )
    assert err.value.code == "routing_unavailable" and err.value.status == 502


@respx.mock
def test_tomtom_non_json_body_is_a_502() -> None:
    respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(ProviderError) as err:
        TomTomRouting("k", httpx.Client()).routes(
            DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
        )
    assert err.value.status == 502


@respx.mock
def test_tomtom_retries_once_on_5xx_then_succeeds() -> None:
    route = respx.get(url__startswith=BASE_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=load_fixture("tomtom_denver_slc.json")),
        ]
    )
    out = TomTomRouting("k", httpx.Client()).routes(
        DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
    )
    assert len(out) == 3 and route.call_count == 2


@respx.mock
def test_tomtom_retries_once_on_timeout_then_gives_up() -> None:
    route = respx.get(url__startswith=BASE_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(ProviderError) as err:
        TomTomRouting("k", httpx.Client()).routes(
            DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
        )
    assert err.value.code == "routing_unavailable"
    assert route.call_count == 2  # bounded: one retry, no more


@respx.mock
def test_tomtom_does_not_retry_quota_errors() -> None:
    route = respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(ProviderError):
        TomTomRouting("k", httpx.Client()).routes(
            DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
        )
    assert route.call_count == 1


@respx.mock
def test_tomtom_error_message_never_echoes_the_key() -> None:
    respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(
            400, json={"detailedError": {"message": "bad key=SECRET123 value"}}
        )
    )
    with pytest.raises(ProviderError) as err:
        TomTomRouting("SECRET123", httpx.Client()).routes(
            DEN, SLC, depart_at=datetime.now(UTC), vehicle_weight_kg=1
        )
    assert "SECRET123" not in err.value.message


@respx.mock
def test_open_meteo_failure_reason_is_reported() -> None:
    respx.get(OM_URL).mock(
        return_value=httpx.Response(
            429, json={"error": True, "reason": "Daily API request limit exceeded"}
        )
    )
    weather = OpenMeteoWeather(httpx.Client(), base_url=OM_URL, retries=1, backoff_s=0)
    start = datetime(2026, 10, 18, tzinfo=UTC)
    out = weather.hourly([LatLon(1, 1)], start, start)
    assert dict(out) == {}
    assert out.errors == ["HTTP 429: Daily API request limit exceeded"]


@respx.mock
def test_open_meteo_non_retryable_reason_is_reported() -> None:
    respx.get(OM_URL).mock(
        return_value=httpx.Response(400, json={"error": True, "reason": "Bad parameter"})
    )
    weather = OpenMeteoWeather(httpx.Client(), base_url=OM_URL, backoff_s=0)
    start = datetime(2026, 10, 18, tzinfo=UTC)
    assert weather.hourly([LatLon(1, 1)], start, start).errors == ["HTTP 400: Bad parameter"]
