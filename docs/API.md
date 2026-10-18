# API reference

Base URL in production: `https://murtuza-truck-routing-api.onrender.com`. Locally: `http://127.0.0.1:8000` (the Vite dev server proxies `/api`).

- **Format:** all bodies are JSON.
- **Timestamps:** ISO 8601 and **must include a timezone offset**. A time without an offset is rejected rather than guessed.
- **Units:** distances are in miles, wind in mph, and rain and snow in inches per hour.

| Method | Path | Rate limit |
|---|---|---|
| `GET` | `/api/health/` | none |
| `GET` | `/api/geocode/?q=` | 120 / min |
| `POST` | `/api/plan/` | 20 / min |
| `POST` | `/api/heatmap/` | 20 / min |

---

## `GET /api/health/`

Liveness check, also used to wake the free-tier instance.

```json
{ "status": "ok" }
```

## `GET /api/geocode/?q=denver`

Place autocomplete for North America. `q` must be 2–120 characters.

```json
{ "results": [ { "label": "Denver, Colorado, US", "lat": 39.7392, "lon": -104.9903 } ] }
```

## `POST /api/plan/`

Plans up to three truck routes and scores the weather along each.

**Request**

```json
{
  "origin": { "label": "Denver, Colorado, US", "lat": 39.7392, "lon": -104.9903 },
  "destination": { "label": "Salt Lake City, Utah, US", "lat": 40.7608, "lon": -111.891 },
  "departure_time": "2026-10-19T14:00:00-06:00",
  "load_weight_lb": 36000,
  "sample_interval_mi": 25,
  "wind_metric": "gust"
}
```

| Field | Rules |
|---|---|
| `origin`, `destination` | `label` (at most 200 characters), `lat` (−90 to 90), `lon` (−180 to 180). Origin and destination must be at least 1 mile apart. |
| `departure_time` | Timezone-aware; from 1 h in the past to 7 days ahead |
| `load_weight_lb` | 0–80,000 |
| `sample_interval_mi` | `10`, `25` or `50` |
| `wind_metric` | `gust` (default) or `sustained`: the wind reading the rules use |

**Response** (abridged)

```json
{
  "generated_at": "2026-10-19T19:58:12Z",
  "request": { "...": "the validated request, echoed" },
  "recommended_route_id": "B",
  "recommendation": {
    "status": "recommended",
    "route_id": "B",
    "none_reason": null,
    "reason": "Route B beats Route C on travel time (8h 01m vs 8h 58m).",
    "exclusions": [ { "route_id": "A", "reason": "Route A is not eligible: No Travel conditions on 400.0 mi (safety constraint)." } ],
    "warnings": [],
    "ranking": ["Severe miles", "High miles", "average risk", "travel time"]
  },
  "routes": [
    {
      "id": "B",
      "source": "routing_api",
      "rank": 1,
      "eligibility": "eligible",
      "waypoint": null,
      "distance_mi": 526.3,
      "duration_s": 28860,
      "arrival_time": "2026-10-19T22:01:00Z",
      "geometry": "<encoded polyline, precision 5>",
      "summary": {
        "miles_by_level": { "low": 526.3, "moderate": 0, "high": 0, "severe": 0, "no_travel": 0 },
        "unknown_miles": 0,
        "forecast_coverage": 1.0,
        "avg_risk": 0.0,
        "max_level": "low"
      },
      "segments": [ { "level": "low", "start_mile": 0, "end_mile": 526.3, "geometry": "<polyline>" } ],
      "checkpoints": [
        {
          "index": 3,
          "mile": 75.0,
          "lat": 39.6114, "lon": -106.0431,
          "eta": "2026-10-19T15:16:00Z",
          "forecast_hour": "2026-10-19T16:00:00Z",
          "weather_cell": { "lat": 39.5, "lon": -106.0 },
          "weather": { "wind_mph": 6.0, "gust_mph": 12.0, "rain_in_hr": 0.02, "snow_in_hr": 0.0 },
          "weather_source": { "wind_mph": "weatherapi", "gust_mph": "weatherapi", "rain_in_hr": "weatherapi", "snow_in_hr": "weatherapi" },
          "risk": {
            "level": "low",
            "score": 0,
            "reasons": [],
            "factors": [
              { "name": "wind", "label": "gusts", "value": 12, "unit": "mph", "base_level": "low", "level": "low", "load_rule": null }
            ]
          }
        }
      ]
    }
  ],
  "notices": [],
  "meta": {
    "routing_lookups": 1,
    "checkpoints": 67,
    "weather": { "cells": 59, "cached": 0, "fetched": 59, "failed": 0, "incomplete": 0, "providers": [ "..." ] },
    "weather_sources": ["weatherapi"],
    "total_ms": 3819
  }
}
```

| Field | Meaning |
|---|---|
| `recommendation.status` | `recommended`, `provisional` (no route has a complete forecast, so the pick is labeled provisional), or `none`, in which case `recommended_route_id` is null |
| `recommendation.none_reason` | Only when the status is `none`: `no_travel` (every route has No Travel miles) or `no_forecast` (too little weather data to assess any route) |
| `routes[].source` | `routing_api` (a TomTom route or alternative) or `detour` (TomTom routing through a waypoint placed by the app) |
| `routes[].eligibility` | `eligible`, `no_travel`, `incomplete_forecast` or `insufficient_forecast` (less than 50 % of the route forecast) |
| `routes[].rank` | Position after the eligibility constraint and the four ranking criteria |
| `checkpoints[].forecast_hour` | The forecast hour used: the ETA rounded up (each value covers the hour ending at this time) |
| `checkpoints[].weather` | `null` when no provider had every value for that cell and hour. The checkpoint is then unscored, not assumed safe. |
| `checkpoints[].weather_source` | The provider behind each value: `weatherapi`, `nws` or `open-meteo` |
| `checkpoints[].risk.factors` | Each factor's reading, its level from the table (`base_level`), the level after load rules (`level`), and the load rule text if one applied |
| `notices` | Plain-language notes, for example a detour route, a weather fallback, or cells without data |
| `meta` | Request accounting: routing lookups, weather cells cached, fetched and failed per provider, and timings |

Risk levels are `low`, `moderate`, `high`, `severe` and `no_travel`, scored 0–4.

## `POST /api/heatmap/`

Hourly weather frames over the trip corridor, for the 0–48 h slider.

**Request**

```json
{
  "routes": ["<encoded polyline>", "<encoded polyline>"],
  "departure_time": "2026-10-19T14:00:00-06:00",
  "load_weight_lb": 36000,
  "wind_metric": "gust"
}
```

`routes` holds 1–3 encoded polylines (the `geometry` of each planned route).

**Response**

```json
{
  "hours": ["2026-10-19T20:00:00Z", "... 49 hours"],
  "points": [[40.75, -111.75], "..."],
  "grid_step_deg": 0.25,
  "levels": ["low", "moderate", "high", "severe", "no_travel"],
  "frames": {
    "risk": [[0, 1, null, "..."], "... one row per hour"],
    "gust": [["mph per point"]],
    "rain": [["in/hr per point"]],
    "snow": [["in/hr per point"]]
  },
  "point_sources": ["weatherapi", "weatherapi+nws", null],
  "meta": { "weather": { "...": "..." }, "weather_sources": ["weatherapi"], "unknown_cells": 0 }
}
```

`frames[metric][hour][point]` is `null` where that point has no forecast for that hour.

## Errors

Every error uses one shape:

```json
{ "error": { "code": "invalid_request", "message": "Check the highlighted fields.", "details": { "departure_time": ["Departure must be within the next 7 days."] } } }
```

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_request` | Validation failed; `details` maps each field to its messages |
| 404 | `not_found` | Unknown path |
| 422 | `routing_rejected` | TomTom couldn't route the trip (for example, no truck-legal road) |
| 429 | `throttled` | Rate limit exceeded |
| 502 | `routing_unavailable`, `geocoding_unavailable` | The routing or place-search provider didn't respond |
| 503 | `routing_not_configured` | The TomTom key is missing or was rejected |
| 500 | `server_error` | Unexpected error; details are logged, not returned |

Weather failures are not errors: affected checkpoints come back with `weather: null`, and a notice explains why.
