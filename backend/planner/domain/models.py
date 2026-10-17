"""Value objects shared by the domain modules. Pure data: no I/O, no Django."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class RiskLevel(IntEnum):
    """Risk levels from the brief. The integer value doubles as the risk score (0-4)."""

    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def slug(self) -> str:
        return self.name.lower()

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


@dataclass(frozen=True, slots=True)
class LatLon:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class WeatherSample:
    """Weather at one place for one forecast hour, in the brief's units."""

    wind_mph: float
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float


@dataclass(frozen=True, slots=True)
class RiskFactor:
    """One input to a checkpoint's risk: its reading and the level the rule table gives it."""

    name: str  # "wind", "rain" or "snow"
    label: str  # "gusts" or "wind" for wind, else same as name
    value: float
    unit: str
    base_level: RiskLevel  # from the threshold table alone
    level: RiskLevel  # after the load rules (only wind can differ)
    load_rule: str | None = None


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel
    reasons: tuple[str, ...] = ()
    factors: tuple[RiskFactor, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteSummary:
    miles_by_level: dict[RiskLevel, float]
    unknown_miles: float
    avg_risk: float
    max_level: RiskLevel | None

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]


@dataclass(slots=True)
class Checkpoint:
    index: int
    mile: float
    point: LatLon
    eta: datetime
    forecast_hour: datetime
    weather_cell: LatLon | None = None
    weather: WeatherSample | None = None
    risk: RiskAssessment | None = None
    owned_miles: float = 0.0


@dataclass(slots=True)
class ScoredRoute:
    """A route reduced to what the recommendation needs."""

    id: str
    duration_s: float
    summary: RouteSummary
    checkpoints: list[Checkpoint] = field(default_factory=list)
