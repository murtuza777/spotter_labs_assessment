import pytest

from planner.domain.models import RiskLevel as L
from planner.domain.models import WeatherSample
from planner.domain.risk import (
    apply_load_rules,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
)


@pytest.mark.parametrize(
    ("mph", "level"),
    [
        (0, L.LOW),
        (24.9, L.LOW),
        (25, L.MODERATE),
        (34.9, L.MODERATE),
        (35, L.HIGH),
        (44.9, L.HIGH),
        (45, L.SEVERE),
        (54.9, L.SEVERE),
        (55, L.NO_TRAVEL),
        (80, L.NO_TRAVEL),
    ],
)
def test_wind_bands(mph: float, level: L) -> None:
    assert classify_wind(mph) == level


@pytest.mark.parametrize(
    ("in_hr", "level"),
    [
        (0, L.LOW),
        (0.0999, L.LOW),
        (0.10, L.MODERATE),
        (0.2499, L.MODERATE),
        (0.25, L.HIGH),
        (0.4999, L.HIGH),
        (0.50, L.SEVERE),
        (1.00, L.SEVERE),
        (1.0001, L.NO_TRAVEL),
    ],
)
def test_rain_bands(in_hr: float, level: L) -> None:
    assert classify_rain(in_hr) == level


@pytest.mark.parametrize(
    ("in_hr", "level"),
    [
        (0, L.LOW),
        (0.49, L.LOW),
        (0.5, L.MODERATE),
        (0.99, L.MODERATE),
        (1.0, L.HIGH),
        (1.99, L.HIGH),
        (2.0, L.SEVERE),
        (3.0, L.SEVERE),
        (3.01, L.NO_TRAVEL),
    ],
)
def test_snow_bands(in_hr: float, level: L) -> None:
    assert classify_snow(in_hr) == level


@pytest.mark.parametrize(
    ("wind_level", "load", "expected"),
    [
        # 45-54 mph + >30,000 lb -> No Travel (strictly greater)
        (L.SEVERE, 30_000, L.SEVERE),
        (L.SEVERE, 30_001, L.NO_TRAVEL),
        # 35-44 mph + >40,000 lb -> Severe (strictly greater)
        (L.HIGH, 40_000, L.HIGH),
        (L.HIGH, 40_001, L.SEVERE),
        # Other levels are never changed by load
        (L.LOW, 80_000, L.LOW),
        (L.MODERATE, 80_000, L.MODERATE),
        (L.NO_TRAVEL, 0, L.NO_TRAVEL),
        # A >30,000 lb load does not touch the 35-44 band, only >40,000 does
        (L.HIGH, 35_000, L.HIGH),
    ],
)
def test_load_rules(wind_level: L, load: float, expected: L) -> None:
    assert apply_load_rules(wind_level, load) == expected


def _w(gust: float = 0, rain: float = 0, snow: float = 0, wind: float = 0) -> WeatherSample:
    return WeatherSample(wind_mph=wind, gust_mph=gust, rain_in_hr=rain, snow_in_hr=snow)


def test_wind_55_is_no_travel_for_any_load() -> None:
    assert assess(_w(gust=55), load_lb=0).level == L.NO_TRAVEL


def test_checkpoint_takes_worst_factor() -> None:
    result = assess(_w(gust=30, rain=0.3, snow=0.6), load_lb=10_000)
    assert result.level == L.HIGH  # wind Moderate, rain High, snow Moderate
    assert len(result.reasons) == 3


def test_calm_weather_is_low_with_no_reasons() -> None:
    result = assess(_w(gust=10, rain=0.01), load_lb=45_000)
    assert result == assess(_w(gust=10, rain=0.01), load_lb=0)
    assert result.level == L.LOW
    assert result.reasons == ()


def test_load_escalation_is_explained() -> None:
    result = assess(_w(gust=47), load_lb=36_000)
    assert result.level == L.NO_TRAVEL
    assert result.reasons == (
        "Gusts 47 mph with load 36,000 lb > 30,000 lb: Severe raised to No Travel",
    )


def test_heavy_load_high_wind_becomes_severe() -> None:
    assert assess(_w(gust=40), load_lb=42_000).level == L.SEVERE
    assert assess(_w(gust=40), load_lb=40_000).level == L.HIGH


def test_sustained_metric_uses_mean_wind() -> None:
    weather = _w(gust=50, wind=20)
    assert assess(weather, 0, wind_metric="gust").level == L.SEVERE
    assert assess(weather, 0, wind_metric="sustained").level == L.LOW


def test_unknown_wind_metric_rejected() -> None:
    with pytest.raises(ValueError):
        assess(_w(), 0, wind_metric="peak")


@pytest.mark.parametrize(
    "weather",
    [
        _w(gust=float("nan")),
        _w(snow=float("nan")),
        _w(rain=float("inf")),
        _w(gust=-1),
        _w(rain=-0.01),
        _w(wind=-5),
    ],
)
def test_invalid_readings_are_rejected_not_classified(weather: WeatherSample) -> None:
    # Regression (audit D2): NaN used to fall through every band to No Travel, and negative
    # values read as Low.
    with pytest.raises(ValueError):
        assess(weather, load_lb=10_000)


@pytest.mark.parametrize("load", [-1, float("nan")])
def test_invalid_load_is_rejected(load: float) -> None:
    with pytest.raises(ValueError):
        assess(_w(gust=40), load_lb=load)


@pytest.mark.parametrize(
    ("gust", "rain", "snow", "load", "level"),
    [
        (47, 0.0, 0.0, 30_000, L.SEVERE),  # load rule needs > 30,000
        (47, 1.5, 0.0, 30_000, L.NO_TRAVEL),  # rain decides
        (40, 0.3, 1.5, 41_000, L.SEVERE),  # wind escalated to Severe beats High rain/snow
        (10, 0.1, 0.5, 80_000, L.MODERATE),  # load never touches rain/snow
        (55, 0.0, 0.0, 0, L.NO_TRAVEL),  # >= 55 mph for any load
        (24.99, 0.0999, 0.499, 79_999, L.LOW),
    ],
)
def test_combinations(gust: float, rain: float, snow: float, load: float, level: L) -> None:
    assert assess(_w(gust=gust, rain=rain, snow=snow), load).level == level


def test_factors_explain_each_input_and_the_load_rule() -> None:
    result = assess(_w(gust=47, rain=0.3, snow=0.0), load_lb=36_000)
    wind, rain, snow = result.factors
    assert (wind.name, wind.label, wind.value, wind.base_level, wind.level) == (
        "wind",
        "gusts",
        47,
        L.SEVERE,
        L.NO_TRAVEL,
    )
    assert wind.load_rule == "load 36,000 lb > 30,000 lb raises Severe to No Travel"
    assert (rain.level, rain.load_rule) == (L.HIGH, None)
    assert snow.level == L.LOW
    assert result.level == L.NO_TRAVEL


def test_factors_without_load_rule() -> None:
    wind = assess(_w(gust=40), load_lb=40_000).factors[0]
    assert wind.level == wind.base_level == L.HIGH and wind.load_rule is None
