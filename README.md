# Weather-Aware Truck Routing

A React + Django app that helps a truck driver pick the **safest** of three truck routes. For each route it checks the forecast at regular checkpoints, **for the hour the truck will actually reach each one**. It scores that weather with the provided wind, rain, snow and load-weight rules, recommends a route, and shows everything on a map with a 0–48 h weather heatmap.

- **Live app:** _add the Vercel URL here_
- **Walkthrough (Loom):** _add the Loom URL here_
- **API:** _add the Render URL here_ (`/api/health/`)

---

## What it does

1. **Input:** origin, destination, departure time, load weight (lb), and checkpoint spacing (10 / 25 / 50 mi). There are also one-click demo trips.
2. **Routes:** TomTom truck routing, using the rig's weight, returns up to 3 alternatives. If it returns fewer distinct routes, the app adds detour routes through waypoints to the side of the main route, so there are still 3 options.
3. **Checkpoints and ETAs:** a checkpoint goes every N miles plus the destination. Each ETA comes from TomTom's travel time at that point along the route, so city stretches are slow and interstates fast, instead of one average speed.
4. **Weather:** the Open-Meteo hourly forecast for the hour each checkpoint is reached: gusts, sustained wind, rain + showers, and snowfall.
5. **Risk:** each checkpoint is classified with the rule table and the load escalations. Every level comes with a plain-English reason, e.g. *"Gusts 47 mph with load 36,000 lb > 30,000 lb: Severe raised to No Travel"*.
6. **Recommendation:** routes are ranked by fewest No Travel miles, then Severe miles, then High miles, then lowest average risk, then shortest drive time. The app explains the pick against **every** other route, e.g. *"Route B beats Route C on travel time (8h 01m vs 8h 59m) and Route A on average risk (0.00 vs 0.14)."*
7. **Map:** shows all routes. The selected route is drawn in risk colors, with clickable checkpoints that show ETA, weather and reasons. A **heatmap** covers the trip corridor with a **0–48 h slider**: play and pause, risk, wind, rain or snow, and a truck marker that moves along the route in step with the slider.

## Rule interpretations

The brief leaves a few cases open. These are the choices made, and they're all covered by unit tests ([`backend/planner/tests`](backend/planner/tests)).

| Topic | Decision |
|---|---|
| **Band edges** | Bands are half-open, lower bound inclusive, so a value on a shared edge goes to the higher level (rain 0.25 in/hr is **High**). The brief writes No Travel as "> 1.00" and "> 3.0", so rain at exactly 1.00 in/hr and snow at exactly 3.0 in/hr stay **Severe**. Wind "25–34" is treated as continuous, so 34.6 mph is Moderate. |
| **Checkpoint risk** | The worst of wind (after the load rules), rain and snow. |
| **Load rules** | These only change the wind level. At 45–54 mph, a load **> 30,000 lb** (strictly) becomes **No Travel**; at 35–44 mph, a load **> 40,000 lb** becomes **Severe**; at ≥ 55 mph it's No Travel for any load. |
| **Which wind** | **Gusts**, because gusts are what blow over high-profile trailers. A form option switches to sustained wind. |
| **Rain** | `rain + showers` (liquid only). Open-Meteo's `precipitation` also counts snow's water equivalent, so it isn't used. |
| **Forecast hour** | Open-Meteo stamps each hour's gusts and precipitation at the **end** of that hour, so a truck passing at 14:20 uses the 15:00 value (the ETA rounded up to the next hour). |
| **Miles per level** | Each checkpoint owns the stretch from the midpoint with the previous checkpoint to the midpoint with the next one. The shares add up exactly to the route length, and one bad checkpoint isn't double-counted. |
| **Average risk** | Miles-weighted mean of the scores Low 0, Moderate 1, High 2, Severe 3, No Travel 4. |
| **Ranking** | **No Travel miles are compared first.** The brief starts at "fewest Severe miles", but read literally that would let a route with No Travel miles beat one with only Severe miles. Miles are compared at 0.1 mi and average risk at 0.01, so float noise counts as a tie and the next criterion decides. |
| **No safe route** | If every route has No Travel miles, the app shows a warning and suggests delaying. |
| **Slider window** | 0–48 h **from the departure time**, so the slider always covers the trip itself. |
| **Routing weight** | Load plus a 35,000 lb empty tractor-trailer (`TRUCK_TARE_LB`), sent to TomTom as gross vehicle weight. The risk rules use the load as entered. |
| **Out of scope** | Hours-of-service rest breaks are not modeled, so ETAs are pure drive time. Departure must be within 7 days, and the load at most 80,000 lb. |

## Architecture

```mermaid
flowchart LR
  UI["React (Vite, TS)<br/>form · route cards · MapLibre map · slider"] -->|POST /api/plan| API
  UI -->|POST /api/heatmap| API
  UI -->|GET /api/geocode| API
  subgraph API["Django + DRF"]
    V[views + serializers] --> S[services<br/>plan_trip · heatmap · weather cache]
    S --> D[domain — pure Python<br/>geo · sampling · eta · risk · scoring · recommend · corridor]
    S --> P[providers<br/>tomtom · openmeteo · photon]
  end
  P --> TT[(TomTom truck routing)]
  P --> OM[(Open-Meteo forecast)]
  P --> PH[(Photon geocoder)]
```

- **`backend/planner/domain/`** holds all the rule logic as pure functions with no Django and no I/O, and it's unit-tested edge by edge.
- **`providers/`** are the only code that sees vendor JSON. They sit behind Protocols in [`base.py`](backend/planner/providers/base.py), so tests swap in fakes.
- **`services/`** do the orchestration:
  - Weather is looked up on the weather model's own **0.25° grid**. Checkpoints that share a cell share one lookup, and each cell is cached for an hour (checkpoints and heatmap share the cache).
  - Weather calls are batched and run with limited parallelism, retrying on 429 and 503.
  - A cell that still fails is marked **unknown**: its miles aren't scored, and the UI says so, so one bad cell doesn't fail the whole plan.
- **Errors** always come back in the same shape, `{"error": {"code", "message", "details?"}}`, which the form maps onto its fields.

### Why these providers

| Need | Choice | Why |
|---|---|---|
| Routing | **TomTom** `travelMode=truck` | Handles truck weight, up to 5 alternatives, and gives travel time at each point (for real ETAs). Free tier, no card. OpenRouteService was rejected because it caps alternatives at 100 km. |
| Weather | **Open-Meteo** `gfs_seamless` | Free, no key, hourly gusts, rain and snow, many points per request. MET Norway was rejected because it has no gusts and no rain/snow split outside the Nordics. |
| Geocoding | **Photon** | Free autocomplete over OpenStreetMap data, with no key. |
| Basemap | **OpenFreeMap** + **MapLibre GL** | Free vector tiles, WebGL rendering, no token. |

## Map performance

The map is half the grade, so it was measured rather than assumed.

- **Everything on the map is a WebGL layer**: routes, risk segments, checkpoints and the heatmap. Only the truck and the two trip endpoints are DOM markers.
- **The slider never changes data-driven paint.** In MapLibre, changing a data-driven paint property (like `heatmap-weight`) makes it pause and re-tile the source in its worker. Doing that on every slider frame stutters. Instead:
  - **The heatmap is 49 layers, one per forecast hour, built once.** The slider only changes `heatmap-opacity`, cross-fading the two neighboring hours, and MapLibre skips any layer whose opacity is 0.
  - **Checkpoints near the slider's time** are highlighted through **feature-state**, which costs no re-tiling.
  - **Measured:** 0 source reloads over 40 slider moves, and about 7 ms per move in the dev build.
- **Heatmap math** ([`lib/heatmap.ts`](frontend/src/lib/heatmap.ts)):
  - **One color scale:** every metric is mapped onto the 0–4 risk scale, so the same color means the same level whichever metric is shown, and the legend applies to all of them.
  - **Radius and intensity:** both are derived from the grid spacing so the summed Gaussian kernels reproduce the grid values at any zoom. Without this, the heatmap breaks into blobs when zoomed in.
- **Payloads:** geometry is simplified on the server (Douglas–Peucker, 30 m tolerance) and sent as encoded polylines, and responses are gzipped. The heatmap is about 6 KB on the wire.
- **Loading:** the map and MapLibre code are loaded lazily, so the form is usable straight away. The first page load also pings `/api/health/` to wake a sleeping free-tier backend.

## Run locally

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 20+, and a free [TomTom key](https://developer.tomtom.com) (no card needed).

```bash
cd backend
cp .env.example .env          # set TOMTOM_API_KEY
uv sync
uv run python manage.py runserver        # http://127.0.0.1:8000
```

```bash
cd frontend
npm install
npm run dev                              # http://localhost:5173 (proxies /api to :8000)
```

## Tests and checks

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

- **Backend:** 125 tests. They cover every threshold edge (24.9/25/34.9/35…, rain 0.0999/0.10/…/1.00/1.0001), the load edges (30,000 vs 30,001 and 40,000 vs 40,001), each tie-breaker, owned-miles sums, the round-up forecast-hour rule, how ETA-based sampling changes the risk, a storm on the fastest route flipping the recommendation, cache reuse, the detour fallback, provider parsing and retries against recorded fixtures, and the API's validation and error shapes.
- **Frontend:** unit tests for polyline decoding, the heatmap weights and cross-fade, and the truck position.
- **CI:** [GitHub Actions](.github/workflows/ci.yml) runs both suites on every push.

## Deploy

- **API (Render):** New → Blueprint → this repo ([`render.yaml`](render.yaml)). Set `TOMTOM_API_KEY`, and set `CORS_ALLOWED_ORIGINS` to the Vercel URL.
- **Frontend (Vercel):** import the repo with root directory `frontend`, and set `VITE_API_BASE_URL` to the Render URL.
- **Keep warm (optional):** set the repository variable `API_HEALTH_URL`, and [keep-warm.yml](.github/workflows/keep-warm.yml) pings the API every 10 min so reviewers don't hit a cold start.

## Limitations and next steps

- **First-request latency:** Open-Meteo's free tier was overloaded during development (about 0.2–0.5 s per location), so an uncached plan can take 15–30 s. Repeat plans come from the cache in about 3 s. With a paid key or a self-hosted Open-Meteo, this would be about 1 s.
- **Hours-of-service ETAs** (breaks after 8 h, rest after 11 h) would make long-trip ETAs, and so the forecast hours, more realistic.
- **"Leave later?" suggestions:** re-score departures at +2, +4 and +6 h and suggest the safest window.
- **Shareable plan URLs**, and generating the TypeScript API types from an OpenAPI schema.
