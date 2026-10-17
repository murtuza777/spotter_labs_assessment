import httpx
import pytest
import respx

from planner.providers.base import Place, ProviderError
from planner.providers.fallback import FallbackGeocoder
from planner.providers.tomtom_search import BASE_URL, TomTomGeocoder


@respx.mock
def test_tomtom_search_labels_and_dedupes() -> None:
    result = {
        "type": "Geography",
        "address": {"freeformAddress": "Salt Lake City, UT", "countryCode": "US"},
        "position": {"lat": 40.758, "lon": -111.888},
    }
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"results": [result, result, {"address": {}}]})
    )
    places = TomTomGeocoder("k", httpx.Client()).search("salt lake", limit=5)
    assert places == [Place("Salt Lake City, UT, US", 40.758, -111.888)]
    request = route.calls.last.request
    assert request.url.raw_path.split(b"?")[0].endswith(b"/salt%20lake.json")
    assert request.url.params["countrySet"] == "US,CA,MX"
    assert request.url.params["typeahead"] == "true"


@respx.mock
def test_tomtom_search_failure_is_provider_error() -> None:
    respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(ProviderError):
        TomTomGeocoder("k", httpx.Client()).search("x")


def test_tomtom_search_without_key() -> None:
    with pytest.raises(ProviderError) as err:
        TomTomGeocoder("", httpx.Client()).search("x")
    assert err.value.status == 503


class _Geo:
    def __init__(self, name: str, fail: bool = False):
        self.name = name
        self.fail = fail
        self.calls = 0

    def search(self, query: str, limit: int = 6) -> list[Place]:
        self.calls += 1
        if self.fail:
            raise ProviderError("geocoding_unavailable", f"{self.name} down")
        return [Place(self.name, 0, 0)]


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_fallback_uses_next_geocoder_and_skips_failed_one_during_cooldown() -> None:
    primary, secondary, clock = _Geo("photon", fail=True), _Geo("tomtom"), _Clock()
    geo = FallbackGeocoder(
        [("photon", primary), ("tomtom", secondary)], cooldown_s=600, clock=clock
    )

    assert geo.search("denver")[0].label == "tomtom"
    assert geo.search("denver")[0].label == "tomtom"
    assert primary.calls == 1  # skipped on the second search

    clock.t += 601
    primary.fail = False
    assert geo.search("denver")[0].label == "photon"  # retried after the cooldown


def test_fallback_raises_when_all_fail() -> None:
    geo = FallbackGeocoder([("a", _Geo("a", fail=True)), ("b", _Geo("b", fail=True))])
    with pytest.raises(ProviderError):
        geo.search("x")
    with pytest.raises(ProviderError):
        geo.search("x")  # all cooling down: still tries rather than failing silently


def test_fallback_needs_a_geocoder() -> None:
    with pytest.raises(ValueError):
        FallbackGeocoder([])
