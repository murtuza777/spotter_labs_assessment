"""Hourly weather frames over the trip corridor for the 0-48 h heatmap slider."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from planner.domain.corridor import corridor_grid
from planner.domain.models import LatLon
from planner.domain.risk import assess
from planner.domain.timebucket import forecast_hour_for
from planner.services.weather import WeatherService

HEATMAP_HOURS = 48


@dataclass(slots=True)
class Heatmap:
    hours: list[datetime]
    points: list[LatLon]
    grid_step_deg: float
    # frames[metric][hour_index][point_index]; None where weather is unavailable
    frames: dict[str, list[list[float | None]]]


class HeatmapBuilder:
    def __init__(self, weather: WeatherService, *, buffer_mi: float = 60.0, max_points: int = 220):
        self._weather = weather
        self._buffer_mi = buffer_mi
        self._max_points = max_points

    def build(
        self,
        routes: list[list[LatLon]],
        departure: datetime,
        load_lb: float,
        wind_metric: str = "gust",
    ) -> Heatmap:
        step, points = corridor_grid(
            routes,
            buffer_mi=self._buffer_mi,
            base_step_deg=self._weather.grid_deg,
            max_points=self._max_points,
        )
        first = forecast_hour_for(departure)
        hours = [first + timedelta(hours=h) for h in range(HEATMAP_HOURS + 1)]
        cells = [self._weather.cell_for(p) for p in points]
        series = self._weather.series_for(cells, hours[0], hours[-1])

        frames: dict[str, list[list[float | None]]] = {
            "risk": [],
            "gust": [],
            "rain": [],
            "snow": [],
        }
        for hour in hours:
            risk_row, gust_row, rain_row, snow_row = [], [], [], []
            for cell in cells:
                s = series.get(cell)
                w = s.at(hour) if s else None
                if w is None:
                    risk_row.append(None)
                    gust_row.append(None)
                    rain_row.append(None)
                    snow_row.append(None)
                    continue
                risk_row.append(int(assess(w, load_lb, wind_metric).level))
                gust_row.append(round(w.gust_mph if wind_metric == "gust" else w.wind_mph))
                rain_row.append(round(w.rain_in_hr, 3))
                snow_row.append(round(w.snow_in_hr, 2))
            frames["risk"].append(risk_row)
            frames["gust"].append(gust_row)
            frames["rain"].append(rain_row)
            frames["snow"].append(snow_row)
        return Heatmap(hours=hours, points=points, grid_step_deg=step, frames=frames)
