"""Weather risk classification, exactly as specified in docs/IMPLEMENTATION_PLAN.md section 2.

Bands are half-open with the lower bound inclusive, so a value on a shared edge goes to the
higher level (rain 0.25 in/hr is High). The brief writes the No Travel bands as "> 1.00" and
"> 3.0", so 1.00 in/hr rain and 3.0 in/hr snow are still Severe.
"""

from planner.domain.models import RiskAssessment, RiskLevel, WeatherSample

L = RiskLevel

# (exclusive upper bound, level) pairs, checked in order.
_WIND_BANDS = ((25.0, L.LOW), (35.0, L.MODERATE), (45.0, L.HIGH), (55.0, L.SEVERE))
_RAIN_BANDS = ((0.10, L.LOW), (0.25, L.MODERATE), (0.50, L.HIGH))
_SNOW_BANDS = ((0.5, L.LOW), (1.0, L.MODERATE), (2.0, L.HIGH))
_RAIN_SEVERE_MAX = 1.00
_SNOW_SEVERE_MAX = 3.0

NO_TRAVEL_LOAD_LB = 30_000  # 45-54 mph and load above this -> No Travel
SEVERE_LOAD_LB = 40_000  # 35-44 mph and load above this -> Severe

# Which wind reading the rules use. Gusts are what push high-profile trailers over, so they
# are the default; "sustained" switches the rule input to the 10 m mean wind speed.
WIND_METRICS = ("gust", "sustained")


def _banded(value: float, bands: tuple[tuple[float, RiskLevel], ...]) -> RiskLevel | None:
    for upper, level in bands:
        if value < upper:
            return level
    return None


def classify_wind(mph: float) -> RiskLevel:
    level = _banded(mph, _WIND_BANDS)
    return L.NO_TRAVEL if level is None else level


def classify_rain(in_hr: float) -> RiskLevel:
    level = _banded(in_hr, _RAIN_BANDS)
    if level is not None:
        return level
    return L.SEVERE if in_hr <= _RAIN_SEVERE_MAX else L.NO_TRAVEL


def classify_snow(in_hr: float) -> RiskLevel:
    level = _banded(in_hr, _SNOW_BANDS)
    if level is not None:
        return level
    return L.SEVERE if in_hr <= _SNOW_SEVERE_MAX else L.NO_TRAVEL


def apply_load_rules(wind_level: RiskLevel, load_lb: float) -> RiskLevel:
    """Escalate the wind level for heavy loads. Only wind is affected by load."""
    if wind_level == L.SEVERE and load_lb > NO_TRAVEL_LOAD_LB:
        return L.NO_TRAVEL
    if wind_level == L.HIGH and load_lb > SEVERE_LOAD_LB:
        return L.SEVERE
    return wind_level


def assess(weather: WeatherSample, load_lb: float, wind_metric: str = "gust") -> RiskAssessment:
    """Checkpoint risk = the worst of the wind (after load rules), rain and snow levels."""
    if wind_metric not in WIND_METRICS:
        raise ValueError(f"wind_metric must be one of {WIND_METRICS}")
    wind = weather.gust_mph if wind_metric == "gust" else weather.wind_mph
    wind_name = "Gusts" if wind_metric == "gust" else "Wind"

    base_wind = classify_wind(wind)
    wind_level = apply_load_rules(base_wind, load_lb)
    rain_level = classify_rain(weather.rain_in_hr)
    snow_level = classify_snow(weather.snow_in_hr)

    reasons: list[str] = []
    if wind_level != base_wind:
        limit = NO_TRAVEL_LOAD_LB if wind_level == L.NO_TRAVEL else SEVERE_LOAD_LB
        reasons.append(
            f"{wind_name} {wind:.0f} mph with load {load_lb:,.0f} lb > {limit:,} lb: "
            f"{base_wind.label} raised to {wind_level.label}"
        )
    elif wind_level > L.LOW:
        reasons.append(f"{wind_name} {wind:.0f} mph: {wind_level.label}")
    if rain_level > L.LOW:
        reasons.append(f"Rain {weather.rain_in_hr:.2f} in/hr: {rain_level.label}")
    if snow_level > L.LOW:
        reasons.append(f"Snow {weather.snow_in_hr:.2f} in/hr: {snow_level.label}")

    return RiskAssessment(level=max(wind_level, rain_level, snow_level), reasons=tuple(reasons))
