# Implementation Plan — Weather-Aware Truck Routing

> **Status, 2026-10-17:** Phases 0–8, 10 and 11 (docs) are built, tested and pushed. Phase 9's Render Blueprint is ready and validated; the services get created from it with one click. The Loom is still to record. The time log is in [PROGRESS.md](PROGRESS.md).
> Changes from the original plan: Open-Meteo uses `gfs_seamless` on its 0.25° grid (§3). The heatmap is 49 layers whose opacity cross-fades, rather than one layer whose weight is re-evaluated (§4.5). Hosting is all on Render: a static site for the frontend and a Docker web service for the API. The frontend calls the API directly with CORS.

Spotter AI · Full Stack Developer assessment · started 2026-10-17
**Budget:** at most 16 work hours over at most 4 days.
**Deliverables:** GitHub repo, hosted app, 5–10 min Loom walkthrough.

---

## 1. What we are building

A React + Django web app that helps a truck driver pick the **safest** route, weighing weather, load weight and travel time.

**Input:** origin, destination, departure date/time, load weight (lb), and the checkpoint interval (10 / 25 / 50 mi).

**Output:**

1. **3 route options** from a routing API.
2. **Checkpoints** every N miles on each route. Each one gets the forecast for the hour the truck is expected to **be there**, not the departure hour.
3. A **risk level** per checkpoint from the provided rules, including the load-weight escalations.
4. One **recommended route**, picked by the provided priority order, with a plain-English reason.
5. A **map** showing all routes, checkpoints, risk levels, ETAs and route summaries.
6. A **weather heatmap** over the trip corridor, with a **0–48 h forecast slider**.

### How it is graded, and where the hours go

| Weight | Area | What that means for us |
|---|---|---|
| **40%** | Routes, weather, risk and recommendation logic | Pure, fully unit-tested domain modules. Boundary values handled explicitly. Every assumption documented. |
| **40%** | UI, map and heatmap smoothness and performance | WebGL layers only (no DOM markers per checkpoint). The slider changes paint properties, never data. Precomputed frames. 60 fps target. |
| 15% | Code quality | Clear layers (domain / providers / services / API). Typed API contract. Lint and tests in CI. |
| 5% | Docs and walkthrough | README with architecture, assumptions and how to run. Scripted Loom. |

> "Prioritize correctness and clarity over extra features." Anything marked **Stretch** below happens only after the core is deployed.

---

## 2. Requirements, made precise

The brief leaves some cases open. These are the interpretations we will implement, test, and state in the README.

### 2.1 Risk thresholds: half-open intervals, lower bound inclusive

| Level (score) | Wind (mph) | Rain (in/hr) | Snow (in/hr) |
|---|---|---|---|
| Low (0) | < 25 | < 0.10 | < 0.5 |
| Moderate (1) | 25 ≤ w < 35 | 0.10 ≤ r < 0.25 | 0.5 ≤ s < 1.0 |
| High (2) | 35 ≤ w < 45 | 0.25 ≤ r < 0.50 | 1.0 ≤ s < 2.0 |
| Severe (3) | 45 ≤ w < 55 | 0.50 ≤ r ≤ 1.00 | 2.0 ≤ s ≤ 3.0 |
| No Travel (4) | ≥ 55 | > 1.00 | > 3.0 |

- The table's ranges overlap at their edges: rain 0.25 is listed under both Moderate and High. We resolve shared edges **upward**. The one exception is the Severe/No Travel edge, where the brief says "> 1.00" and "> 3.0", so 1.00 and 3.0 stay Severe.
- Wind ranges like "25–34" are treated as continuous, so 34.6 mph is Moderate.
- **Checkpoint risk = the worst of the wind, rain and snow levels**, after the load rules below are applied.

### 2.2 Load rules (they only change the wind level)

- Wind ≥ 55 mph → **No Travel**, whatever the load. The base table already gives this.
- 45 ≤ wind < 55 **and load > 30,000 lb** → **No Travel**. Without the load rule this would be Severe.
- 35 ≤ wind < 45 **and load > 40,000 lb** → **Severe**. Without the load rule this would be High.
- "> 30,000" is strict, so exactly 30,000 lb does not escalate. Both edges get unit tests.
- Each checkpoint records **why** it got its level, for example `wind 47 mph + load 36,000 lb > 30,000 → No Travel`. The UI shows this.

### 2.3 Weather inputs, from Open-Meteo hourly data

| Rule input | Open-Meteo field | Notes |
|---|---|---|
| Wind | `wind_gusts_10m`, in mph | Gusts are what push high-profile trucks over, so we use the safer reading. A config flag can switch to sustained `wind_speed_10m`. Both values are shown in the UI. |
| Rain | `rain` + `showers`, in inches | Liquid only. We don't use `precipitation` because it also counts snow's water equivalent. |
| Snow | `snowfall`, in inches | Request with `precipitation_unit=inch`. In the spike, confirm the unit (otherwise cm ÷ 2.54). |

- Open-Meteo stamps these hourly fields at the **end** of the hour they cover ("preceding hour sum/max"). A truck passing at 14:20 is inside 14:00–15:00, so we read the value stamped **15:00**: `ceil(ETA to the hour)`. A unit test covers this.
- All times are UTC internally (`timezone=GMT`). The UI shows local times.

### 2.4 Checkpoints and ETAs

- Checkpoints sit at 0, N, 2N, … miles along the route polyline (haversine distance), **plus the destination**.
- ETA at mile d = departure + `t(d)`. `t` is a piecewise-linear time-vs-distance curve built from TomTom's per-point travel times (`extendedRouteRepresentation=travelTime`, with guidance instructions as a fallback). This way the truck is slower in cities and faster on interstates, rather than averaging one speed.
- Driver rest breaks (Hours of Service) are **not** modeled. The ETA is pure drive time. This is stated in the README; an HOS model is Stretch.

### 2.5 Route scoring

- **Miles at each level:** a checkpoint "owns" the route from the midpoint with the previous checkpoint to the midpoint with the next one. The first checkpoint starts at mile 0 and the last ends at the destination. The owned miles add up exactly to the route length, so a single bad checkpoint isn't double-counted.
- **Average risk** = Σ(score × miles) / total miles, using scores 0–4.
- **Recommendation:** sort the routes lexicographically by
  1. **No Travel miles**, fewest first. The brief doesn't list this, but No Travel is worse than Severe, so it has to come first. Otherwise a route with No Travel miles could beat one with Severe miles.
  2. **Forecast coverage**: fully forecast routes before routes with unforecast miles *(added in the audit, D1)*. Unknown miles are unscored, so without this gate a route whose weather couldn't be fetched would look as safe as calm weather. It sits after No Travel so a route with *known* No Travel never wins over one with unknowns.
  3. **Severe miles**, fewest first
  4. **High miles**, fewest first
  5. **Average risk**, lowest first (compared at 2 decimal places, so tiny float differences count as a tie)
  6. **Travel time**, shortest first

  Miles are compared at 0.1 mi precision. Criteria 3–6 are exactly the brief's order. This ordering is how the brief's "balance weather risk and travel time" works: travel time breaks ties once the risk is equal.
- **Explanation:** compare the winner with every other route at the first criterion where they differ, for example "Route B beats Route A on Severe miles (0.0 mi vs 18.0 mi)". If **every** route has No Travel miles, show a warning banner ("No safe route at this departure time") and call the pick the "least risky option".

### 2.6 The heatmap slider

- The slider runs over **hours 0–48 from the departure time**. If the departure is "now", that is the usual forecast lead time. Each step shows its clock time.
- The heatmap values are risk scores (using the same rules and load) on a grid of points covering the corridor. A selector can switch it to show raw wind, rain or snow.
- A **truck-position marker** moves along the selected route in step with the slider. Seeing the truck enter the weather at the same hour shows why we sample at the ETA.

### 2.7 Input validation

- Departure must be between now − 1 h and now + 7 days. This keeps the trip plus the 48 h window inside Open-Meteo's 16-day forecast.
- Load must be between 0 and 80,000 lb. That is the cap in the input form; a soft warning above 80,000 is Stretch.
- Origin and destination come from geocoder picks, North America only, and must be different places.

---

## 3. Tech choices (final)

| Concern | Choice | Why |
|---|---|---|
| Routing | **TomTom Routing API** `calculateRoute` with `travelMode=truck`, `vehicleWeight` (kg), `maxAlternatives=2`, `departAt`, `traffic=true`, `extendedRouteRepresentation=travelTime` | Truck-aware with weight, up to 5 alternatives, per-point travel times, plans departures from historic traffic. Free tier is 20K req/month with no credit card. |
| Weather | **Open-Meteo** forecast API (many points per request) | Free, no key, hourly gusts, rain, showers and snowfall, 16-day horizon. Free tier: 600 calls/min, 5K/hour, 10K/day, non-commercial. |
| Geocoding | **Photon** (komoot, OpenStreetMap), with TomTom Fuzzy Search as fallback | Keyless autocomplete. TomTom Search only gives 2.5K free requests a month, too few for typeahead. |
| Basemap | **OpenFreeMap** vector tiles (`positron` style) | Free, no key, works with MapLibre. |
| Map engine | **MapLibre GL JS 6** + `react-map-gl/maplibre` | WebGL. Native `heatmap`, `line` and `circle` layers. No token. |
| Frontend | Vite 8, React 19, TypeScript (strict), Tailwind 4, TanStack Query 5, Zustand 5, date-fns 4 | Already scaffolded. |
| Backend | Python 3.12, Django 5.2 LTS, DRF 3.18, httpx, django-environ, django-cors-headers, gunicorn | Already scaffolded. Stateless, so no database models. |
| Tests | pytest, pytest-django, respx (HTTP mocks with recorded fixtures); Vitest | |
| Lint | ruff (backend), oxlint and `tsc` (frontend) | |
| Hosting | **Render** for everything, from one Blueprint: a static site (frontend) and a Docker web service (Django). The frontend calls the API directly, with CORS. | One provider and one Blueprint. The static site is served from Render's CDN and never sleeps. The free API sleeps when idle, so the page pings `/api/health/` on load and an optional GitHub Actions cron keeps it warm during review. |

### Rejected options

- **OpenRouteService:** alternative routes are capped at 100 km, which is useless for trucking.
- **OSRM demo server:** no truck profile, and production use isn't allowed.
- **Mapbox Directions:** good, but no truck mode and it needs a token tied to a card.
- **HERE:** truck routing is excellent, but signup and the free tier are less certain. It stays the backup routing provider behind the same interface.

### API budget per plan request

- **Routing:** 1 TomTom call, or up to 3 if we need the fallback alternatives (§4.2).
- **Weather:** checkpoint coordinates snapped to the **0.25° GFS grid** (`models=gfs_seamless`) and deduplicated. Heatmap grid points sit on the same grid, so they share the cache. Batches of about 25 locations, at most 3 requests in parallel, retrying on 429/503 with backoff.
- **Caching:** each cell's hourly series is cached for 60 min. Cells that still fail are marked *unknown*; their miles aren't scored, and the UI shows a notice.

> **Phase 1 finding (2026-10-17):** Open-Meteo's free tier answered with "The service is overloaded" (503). With the default model, latency was about 0.5 s **per location**; parallel requests got 429. Choosing `gfs_seamless` and snapping to its native 0.25° grid cut the location count and latency several times over without losing resolution. MET Norway was fast but has no gusts or rain/snow split outside the Nordics, so it was rejected. TomTom truck routing returned 3 routes, with about 100–200 `progress` entries each (`pointIndex`, `distanceInMeters`, `travelTimeInSeconds`). Open-Meteo returns snowfall in inches when `precipitation_unit=inch`.

---

## 4. Architecture

```
frontend (Render static site)             backend (Render, Django/DRF)
┌─────────────────────────┐   /api/*    ┌──────────────────────────────────────────┐
│ TripForm + Autocomplete │ ──────────▶ │ api/ views + serializers (validation)    │
│ RouteList / RouteCard   │             │ services/ plan_trip, heatmap, weather    │
│ TripMap (MapLibre GL)   │ ◀────────── │   (orchestration, batching, caching)     │
│  routes · checkpoints   │    JSON     │ domain/ (pure, no Django, 100% tested)   │
│  heatmap · truck marker │             │   geo · sampling · eta · risk · scoring  │
│ ForecastSlider (0–48h)  │             │   recommend · corridor_grid              │
│ Zustand store           │             │ providers/ tomtom · openmeteo · photon   │
└─────────────────────────┘             └──────────────────────────────────────────┘
```

### 4.1 Backend layout (`backend/planner/`)

```
domain/            # pure functions + dataclasses; no I/O, no Django
  models.py        # LatLon, RouteGeometry, Checkpoint, WeatherSample, RiskLevel (IntEnum), RouteSummary
  geo.py           # haversine, cumulative distances, interpolate_along(polyline, d), bbox, point→polyline distance
  sampling.py      # checkpoint_distances(length, interval) and build_checkpoints(route, interval)
  eta.py           # TimeProfile from (distance, seconds) pairs; eta_at(d)
  risk.py          # classify_wind/rain/snow, apply_load_rules, classify_checkpoint → (level, reasons)
  scoring.py       # owned-miles allocation, miles_by_level, avg_risk, summarize_route
  recommend.py     # rank_routes (lexicographic key) and explain(winner, runner_up)
  corridor.py      # heatmap grid points within X mi of any route, with a point cap
  timebucket.py    # forecast_hour_for(eta): ceil-to-hour rule
providers/
  base.py          # Protocols: RoutingProvider, WeatherProvider, Geocoder; typed DTOs; ProviderError
  tomtom.py        # calculateRoute request/parse (+ via-point fallback alternatives)
  openmeteo.py     # batched multi-location hourly fetch, unit params, response parsing
  photon.py        # autocomplete
services/
  weather.py       # snap + dedupe + cache + concurrent batches → lookup(lat, lon, hour)
  plan_trip.py     # route → checkpoints → ETAs → weather → risk → summaries → recommendation
  heatmap.py       # corridor grid → 49 hourly frames → compact arrays
serializers.py     # PlanRequest and PlaceQuery validation
views.py           # health, geocode, plan, heatmap
tests/             # unit tests per domain module + service tests with respx fixtures
  fixtures/        # recorded TomTom and Open-Meteo JSON from the Phase 1 spike
```

### 4.2 Always returning 3 routes

1. Ask TomTom for `maxAlternatives=2` with `alternativeType=anyRoute`.
2. If fewer than 3 distinct routes come back, generate detour candidates. Offset the midpoint of the main route by ±10–15% of its length, at right angles to it, and route through each point (TomTom waypoints, `origin:via:destination`).
3. Drop near-duplicates. Two routes are duplicates if they share more than 90% of their checkpoints (cells at 0.1°) or differ in length by less than 1%.
4. If there are still fewer than 3, return what we have and set a `notice` explaining why (for example, a short trip on a single road).

### 4.3 API contract (v1)

`GET /api/health/` → `{ "status": "ok" }`

`GET /api/geocode/?q=denver` → `{ "results": [{ "label": "Denver, CO, USA", "lat": 39.74, "lon": -104.99 }] }`

`POST /api/plan/`
```json
{
  "origin":      { "label": "Denver, CO", "lat": 39.7392, "lon": -104.9903 },
  "destination": { "label": "Salt Lake City, UT", "lat": 40.7608, "lon": -111.8910 },
  "departure_time": "2026-10-18T14:00:00Z",
  "load_weight_lb": 36000,
  "sample_interval_mi": 25
}
```
→
```json
{
  "plan_id": "uuid",
  "generated_at": "…Z",
  "recommended_route_id": "B",
  "recommendation": { "reason": "0 Severe miles vs 18 on Route A", "warnings": [] },
  "routes": [{
    "id": "A",
    "distance_mi": 521.4,
    "duration_s": 30420,
    "arrival_time": "…Z",
    "geometry": "<encoded polyline, precision 5, simplified for display>",
    "summary": {
      "miles_by_level": { "low": 400.1, "moderate": 90.0, "high": 13.3, "severe": 18.0, "no_travel": 0 },
      "avg_risk": 0.41, "max_level": "severe", "rank": 2
    },
    "checkpoints": [{
      "mile": 25.0, "lat": 39.9, "lon": -105.4, "eta": "…Z", "forecast_hour": "…Z",
      "weather": { "wind_mph": 21, "gust_mph": 38, "rain_in_hr": 0.02, "snow_in_hr": 0.6 },
      "risk": { "level": "high", "score": 2, "reasons": ["gusts 38 mph → High", "snow 0.6 in/hr → Moderate"] }
    }]
  }],
  "notices": []
}
```

`POST /api/heatmap/` takes the same `departure_time` and `load_weight_lb`, plus the route geometries. It is a separate call so the routes render first and the heatmap streams in after.
```json
{
  "hours": ["…Z", "… 49 entries"],
  "points": [[lat, lon], "…"],
  "grid_step_deg": 0.25,
  "frames": {
    "risk":  [[0,1,0,"…per point"], "… per hour"],
    "gust":  [[…]], "rain": [[…]], "snow": [[…]]
  }
}
```

Errors use one shape: `{ "error": { "code": "routing_unavailable", "message": "…" } }`, with HTTP 400, 422, 502 or 503 as appropriate.

### 4.4 Frontend layout (`frontend/src/`)

```
api/          client.ts, types.ts (mirrors §4.3), queries.ts (TanStack Query hooks)
store/        tripStore.ts (selectedRouteId, hour, heatmapMetric, isPlaying, hoveredCheckpoint)
features/
  planner/    TripForm.tsx, PlaceAutocomplete.tsx (debounced 250 ms, keyboard nav), DemoPresets.tsx
  routes/     RouteList.tsx, RouteCard.tsx, RiskMilesBar.tsx, RecommendationBanner.tsx, CheckpointTimeline.tsx
  map/        TripMap.tsx, layers/{routes,checkpoints,heatmap,truck}.ts, CheckpointPopup.tsx, Legend.tsx
  timeline/   ForecastSlider.tsx (play/pause, keyboard, time labels, departure/arrival ticks)
lib/          risk.ts (levels, colors, labels), format.ts (mi, h:mm, local time), polyline.ts, geo.ts
```

### 4.5 Keeping the map smooth (40% of the grade)

1. **Everything on the map is a WebGL layer:** route lines, checkpoints (`circle`), heatmap, truck. We avoid React `<Marker>`s for checkpoints, because hundreds of DOM nodes would make panning stutter.
2. **Heatmap data is uploaded once.** Each grid point carries the flat properties `h0…h48`. Moving the slider only changes the paint property `heatmap-weight`, set to `["get", "h12"]`. Nothing is re-parsed and no GeoJSON is re-sent. For fractional hours, blend two frames with `(1−t)·hN + t·hN+1`, so playback eases between hours instead of jumping.
3. **The color scale is fixed** across all hours, with a visible legend, so the same color always means the same risk.
4. **The heatmap radius follows the grid spacing at every zoom** (an exponential zoom expression). Without this the heatmap breaks into blobs when zoomed in.
5. **Slider updates are throttled with requestAnimationFrame.** Only the map layer and the time label subscribe to the hour, through a Zustand selector, so the sidebar doesn't re-render.
6. **Selecting a route changes styling only:** filter and paint expressions on features tagged with the route id. Data is not rebuilt.
7. **Geometry is simplified on the server** (Douglas–Peucker, about 30 m tolerance) and sent as an encoded polyline. This shrinks the payload about 10×.
8. **The map code is its own chunk** (dynamic import), so the form appears immediately. Target: Lighthouse performance ≥ 90, and no frame over 16 ms while dragging the slider (checked in the Performance panel).
9. **The UI handles slow and failed requests:** skeleton loaders, then routes appear first and the heatmap after. Every failure shows a readable message.

---

## 5. Phased execution (≈ 14.5 h, with a 1.5 h buffer)

Each phase ends with something that works and a commit. ✅ marks done.

### Day 1 — Foundations and core logic (≈ 5 h)

**Phase 0 — Setup (0.5 h)** ✅ *mostly done in this session*
- [x] Git repo; uv-managed Django 5.2 project (`config/`, `planner/`); Vite React TS app
- [x] Env-driven settings, CORS, DRF, cache, `/api/health/`, and a pytest smoke test
- [x] MapLibre map with OpenFreeMap; Vite `/api` proxy; Tailwind; strict TypeScript
- [ ] Get a TomTom key (developer.tomtom.com, free, no card) → `backend/.env`
- [ ] Push to GitHub; add a GitHub Actions CI job (ruff + pytest; oxlint + tsc + vitest + build)

**Phase 1 — API spike and fixtures (1 h)**
- [ ] Use a script to call TomTom truck routing for 2–3 real trips (Denver→SLC, Chicago→Minneapolis, Dallas→Atlanta). Confirm the alternatives count, `progress` travel times, and that the polyline is complete.
- [ ] Call Open-Meteo with about 100 locations in one request. Confirm the units (snowfall in inches), hour stamps, and response shape.
- [ ] Call Photon autocomplete.
- [ ] Save sanitized responses into `planner/tests/fixtures/`. **Exit:** every assumption in §2.3 and §2.4 is confirmed or corrected in this plan.

**Phase 2 — Domain logic, test-first (2.5 h)** ← *the first 40%*
- [ ] `geo.py` and `sampling.py`: cumulative distance, interpolation, checkpoints at N mi plus the endpoint. Tests: a straight-line route with known length, intervals 10/25/50, a route shorter than N.
- [ ] `eta.py`: time profile and interpolation. Tests: monotonic times, the end equals total duration, a variable-speed profile.
- [ ] `timebucket.py`: ceil-to-hour. Tests: exactly on the hour, :01, :59.
- [ ] `risk.py`: every threshold edge (24.9, 25, 34.9, 35, 44.9, 45, 54.9, 55; rain 0.0999, 0.10, 0.25, 0.50, 1.00, 1.0001; the same for snow), load edges (30,000 vs 30,001; 40,000 vs 40,001), worst-of-three, and the reason text.
- [ ] `scoring.py`: owned-miles allocation sums to the route length; avg risk; miles by level.
- [ ] `recommend.py`: one test per tie-breaker, the No Travel-first rule, the all-No-Travel warning, and the explanation text.
- [ ] **Exit:** `pytest` is green with ~95% coverage on `domain/`.

**Phase 3 — Providers, services, endpoints (1.5 h)**
- [ ] `providers/tomtom.py`, `openmeteo.py` and `photon.py` with timeouts, one retry with backoff, and mapping to `ProviderError`.
- [ ] `services/weather.py`: snap to 0.1°, deduplicate, batch about 100 locations, run in a thread pool, Django cache with a 30 min TTL.
- [ ] `services/plan_trip.py`, including the 3-route fallback (§4.2); `services/heatmap.py` with the corridor grid and 49 frames.
- [ ] Views and serializers for `/api/geocode/`, `/api/plan/` and `/api/heatmap/`, with the shared error shape and DRF throttling.
- [ ] Service tests against the respx fixtures. **Exit:** `curl POST /api/plan/` locally returns 3 ranked routes with real weather.

### Day 2 — The UI (≈ 5 h) ← *the second 40%*

**Phase 4 — Form and data flow (1 h)**
- [ ] `types.ts` matching §4.3, and the TanStack Query hooks.
- [ ] `TripForm`: autocomplete for both ends, `datetime-local` (default: next whole hour), load in lb, the 10/25/50 toggle. Validation messages; Enter submits.
- [ ] `DemoPresets`: 3 one-click example trips for reviewers.

**Phase 5 — Map: routes and checkpoints (1.75 h)**
- [ ] Route layers: inactive routes thin and slate-colored; the selected route drawn as risk-colored segments with a dark casing; clicking a route selects it; A/B/C labels.
- [ ] Checkpoint `circle` layer colored by risk, larger on hover. The popup shows mile, ETA (local time), gust/sustained wind, rain, snow, level and reasons.
- [ ] Fit the view to the routes; a legend for risk colors.

**Phase 6 — Sidebar results (0.75 h)**
- [ ] `RecommendationBanner` (the winner and its reason, or the no-safe-route warning).
- [ ] `RouteCard` × 3: distance, duration, ETA, avg risk, max level, and a `RiskMilesBar` (stacked miles by level). The ⭐ recommended badge and rank. Hovering a card highlights its route.
- [ ] `CheckpointTimeline` for the selected route: a risk strip by mile/ETA; clicking a row flies to that checkpoint.

**Phase 7 — Heatmap and slider (1.5 h)**
- [ ] Fetch the heatmap after the plan arrives; build the GeoJSON once with `h0…h48`.
- [ ] Heatmap layer: weight expression by hour, fixed color ramp matching the risk colors, zoom-scaled radius, opacity control, toggle.
- [ ] `ForecastSlider`: 0–48 h, time label, ticks for departure and the selected route's arrival, play/pause (about 4 h of forecast per second), ← → keys.
- [ ] Truck marker interpolated along the selected route at `departure + hour`. Checkpoints whose ETA is within ±30 min of the slider pulse.
- [ ] Metric selector: Risk / Gusts / Rain / Snow.

### Day 3 — Polish, performance, deploy (≈ 3 h)

**Phase 8 — Performance and UX polish (1.25 h)**
- [ ] Profile slider dragging and panning in Chrome DevTools; fix anything over 16 ms. Lazy-load the map chunk; memoize GeoJSON builders.
- [ ] Loading skeletons, empty state, error states, and a layout that works on a narrow screen (sidebar becomes a bottom sheet under 768 px).
- [ ] Accessibility: labels, focus rings, and risk shown as **text plus color** (never color alone).

**Phase 9 — Deploy (1.25 h)**
- [ ] Backend: `Dockerfile` (uv, gunicorn, 2 workers), Render web service, env vars, `/api/health/` health check.
- [ ] Frontend: Render static site in the same Blueprint, with `VITE_API_BASE_URL` set to the API origin and long cache headers on `/assets/*`.
- [ ] A keep-warm ping every 10 min; an end-to-end smoke test on the live URL with the 3 demo presets.

**Phase 10 — Hardening (0.5 h)**
- [ ] Rate-limit behavior (Open-Meteo 429 → a cached or partial result with a notice), and how the UI handles a missing TomTom key.
- [ ] Final pass with `ruff`, `oxlint`, `tsc`, `pytest` and `vitest`; fix all warnings.

### Day 4 — Docs, Loom, submit (≈ 1.5 h + 1.5 h buffer)

**Phase 11 — README and walkthrough**
- [ ] README: a one-paragraph pitch, screenshots or GIF, live link, architecture diagram, **assumptions** (§2, copied verbatim), API contract, how to run locally, tests, tradeoffs, and what we'd do next.
- [ ] Loom (5–10 min), scripted:
  1. (0:00–1:30) The problem; a live demo of a preset trip.
  2. (1:30–4:00) The logic: ETA-based sampling, risk rules with the load escalation, owned-miles scoring, the ranking and its explanation. Show `risk.py`, `recommend.py` and the tests.
  3. (4:00–6:00) The heatmap slider and the truck marker; why it stays smooth (paint expressions, not data reloads).
  4. (6:00–8:00) Architecture tour, provider choices and fallbacks, deployment.
  5. (8:00–9:00) Tradeoffs and next steps.
- [ ] Before recording, use the heatmap to find a real windy or snowy corridor that day, so the recommendation visibly changes.
- [ ] Submit: GitHub URL, hosted URL and Loom URL in the reply to Ena.

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| TomTom returns fewer than 3 truck alternatives | Detour via-points and deduplication (§4.2); a `notice` in the UI |
| Open-Meteo rate limits (rules for many locations are undocumented) | Snap and deduplicate to 0.1°, cache for 30 min, cap at 600 locations per plan, fetch only the needed hours; on 429, back off and return partial data with a notice |
| Calm weather on demo day makes all routes Low | Pick a real weather corridor before recording; the unit tests show the risk logic. Stretch: a labeled "scenario" mode that injects a storm cell |
| Render cold starts (~30–60 s) | Keep-warm cron; the frontend shows "waking server…" after 3 s |
| Heatmap looks blotchy (density artifacts) | Radius tied to grid spacing at each zoom. Fallback: a canvas `image` source with bilinear-interpolated cells |
| Going over 16 h | Stretch items stay out until Phase 9 is live; track hours in `docs/PROGRESS.md` |

## 7. Stretch (only after a live deploy)

- "Depart later?" suggestions: re-score departures at +2, +4, +6 h and show the safest window.
- An HOS-aware ETA (30 min break after 8 h of driving; 10 h rest after 11 h).
- A labeled weather scenario mode for demos.
- Shareable plan URL (state encoded in the query string).
- Generating `types.ts` from the OpenAPI schema (drf-spectacular + openapi-typescript).

## 8. Definition of done

- [ ] The live app plans a trip from scratch in under 6 s on a warm server, and always shows up to 3 routes, the recommendation and its reason, checkpoints with ETA, weather and risk, and the heatmap with a working 0–48 h slider.
- [ ] All risk and load edge cases are covered by passing tests, and CI is green.
- [ ] The README states every assumption in §2.
- [ ] The Loom is between 5 and 10 minutes.
- [ ] Total time spent is at most 16 h, logged in `docs/PROGRESS.md`.
