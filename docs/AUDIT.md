# Assessment Audit — Weather-Aware Truck Routing

Audited 2026-10-17 against the brief (`fs-assessment-spotter.pdf`) and the live deploy (https://murtuza-truck-routing.onrender.com). Every result below comes from code that was actually run: unit and API tests, probe scripts against the real modules, live TomTom and Open-Meteo calls, and browser runs. Nothing is inferred from the README alone.

Status key: **Pass** = verified by an executed test or probe · **Fixed** = a defect found here, fixed and covered by a regression test · **Partial** = works, with a documented limitation · **Not verified** = could not be executed here.

## 1. Inputs

| Requirement | Where | Verified by | Status |
|---|---|---|---|
| Origin and destination (autocomplete) | `providers/photon.py`, `providers/tomtom_search.py`, `providers/fallback.py`, `PlaceAutocomplete.tsx` | `test_providers`, `test_geocoding`, live `/api/geocode/`, e2e | Pass (Photon was unreachable from Render once, so a TomTom fallback was added) |
| Departure date and time | `serializers._validate_departure`, `TripForm.tsx` | `test_api` | **Fixed D3**: naive timestamps were silently read as UTC; now rejected |
| Load weight (lb) | `PlanRequestSerializer` | `test_api` | Pass: 0–80,000 lb; 0 is valid (empty trailer); negative, NaN and over 80,000 are rejected |
| Checkpoint interval 10 / 25 / 50 mi | `domain/sampling.py`, serializer `ChoiceField` | `test_geo_sampling`, `test_services`, `test_api` | Pass |

## 2. Routes

| Requirement | Where | Verified by | Status |
|---|---|---|---|
| 3 route options from a routing API | `providers/tomtom.py` (`maxAlternatives=2`, truck mode, vehicle weight) | live: 3 TomTom routes for Denver→SLC and Seattle→Spokane | Pass |
| No fake alternatives | `plan_trip._candidate_routes` | `test_services` | Partial, by design: if TomTom returns fewer than 3 distinct routes, extra **real TomTom truck routes through a side waypoint** are added and labeled *Detour* in the card, the API (`source: "detour"`) and a notice. Nothing is fabricated; if detours fail, fewer routes are shown with a notice. |
| Duplicate or near-identical alternatives removed | `_signature` / `_overlap` (≥90 % shared 0.05° cells) | `test_duplicate_alternatives_are_dropped` | Pass |
| Malformed routing responses | `tomtom.parse_route` | probe | **Fixed D4**: a missing `summary` or `latitude` raised `KeyError` (→ 500); malformed routes are now skipped, and a 502 is returned if none are valid |
| Multi-leg (waypoint) routes keep cumulative distance/time | `parse_route` (concatenates legs) | live probe: `progress` indices, distance and time are monotonic across legs | Pass |

## 3. Checkpoints and ETAs

| Requirement | Where | Verified by | Status |
|---|---|---|---|
| Checkpoints follow the route geometry, not a straight line | `geo.cumulative_miles` / `interpolate_along` over the full TomTom polyline | `test_geo_sampling`, `test_services` | Pass |
| Destination always included, no duplicate at exact multiples | `sampling.checkpoint_miles` | `test_geo_sampling` | Pass |
| ETA from the truck's real speed profile | `eta.TimeProfile` from TomTom `progress` (cumulative time at about 100–200 points) | `test_geo_sampling`, `test_services` (ETA at the destination = departure + route duration) | Pass |
| Units (meters → miles, seconds) | `plan_trip._prepare` scales polyline miles to TomTom's official length | `test_services` (owned miles add up to the route distance) | Pass |

## 4. Weather and risk

| Requirement | Where | Verified by | Status |
|---|---|---|---|
| Forecast at each checkpoint's arrival hour | `timebucket.forecast_hour_for` (round up: Open-Meteo values cover the hour *ending* at the stamp) | `test_geo_sampling`, `test_eta_based_sampling_picks_weather_at_arrival_hour` | Pass |
| Wind, rain and snow thresholds exactly as specified | `domain/risk.py` | `test_risk` (every edge) | Pass |
| Load rules (> 30,000 lb at 45–54 mph, > 40,000 lb at 35–44 mph, ≥ 55 mph always) | `risk.apply_load_rules` | `test_risk` (30,000/30,001, 40,000/40,001) | Pass |
| Missing, NaN or negative readings are never treated as safe | `providers/base.HourlySeries.at`, `openmeteo.parse_response`, `risk.assess` | probe | **Fixed D2**: NaN snow or wind was classified **No Travel** and negative values **Low**; invalid readings now count as *unknown* |
| Malformed weather responses | `openmeteo.parse_response` | probe | **Fixed D5**: lists of different lengths or string values made `HourlySeries` crash later; they are now validated per location |
| Few weather calls | `services/weather.py` (0.25° grid snapping, dedupe, per-cell cache, batches of 25, at most 3 in parallel, retries on 429/5xx) | `test_weather_cells_are_snapped_deduped_and_cached`, measurements (section 8) | Pass |

## 5. Recommendation

| Requirement | Where | Verified by | Status |
|---|---|---|---|
| Ranking: Severe miles → High miles → average risk → travel time (lexicographic, not weighted) | `domain/recommend.sort_key` | `test_recommend` | Pass |
| Mileage-based, not checkpoint counts | `scoring.owned_miles` (midpoint ownership) | `test_geo_sampling`, `test_services` | Pass |
| No Travel is safety-critical | `sort_key` puts No Travel miles **before** Severe miles; banner reads "No safe route" when every route has No Travel | `test_recommend` | Pass. The UI now also flags No Travel on each route card. |
| Missing weather is never treated as safe | `sort_key` | probe | **Fixed D1 (P0)**: a route with 90 of 100 mi *unforecast* beat a fully forecast route with 10 Severe mi. Fully assessed routes now rank first, and the explanation says so. |
| The API's route order does not decide the winner | `rank` (stable sort only on full ties) | `test_recommend` | Pass |

## 6. Map, heatmap and slider

| Requirement | Where | Verified by | Status |
|---|---|---|---|
| All routes, checkpoints, risk, ETAs and summaries on the map | `RouteLayers.tsx`, `CheckpointPopup.tsx`, `RouteCard.tsx` | e2e (`plans a trip end to end`, `checkpoint details…`, `fits the map to every route`), live browser run | Pass. **Fixed**: risk miles under 1 mi were rounded to "0" on the cards; they now never round down to 0. |
| Weather heatmap along the corridor | `services/heatmap.py` (corridor grid at 0.25–1° within 60 mi of any route, real Open-Meteo hourly values), `HeatmapLayer.tsx` | `test_heatmap_frames_shape_and_values`, live `/api/heatmap/` (132 points × 49 h, 0 nulls) | Pass. It's a smoothed heatmap of real grid-point forecasts, not a radar field. |
| 0–48 h slider with a displayed time | `ForecastSlider.tsx` (49 hourly frames, cross-faded) | e2e at 0 / 12.5 / 48 h (frame opacities, time label, truck status), 0 source reloads over 40 moves | Pass. **Added**: the truck's position and nearest checkpoint at the slider time, so the heatmap time and the checkpoint ETAs can be read together. |
| Unavailable data shown as unavailable | grey "No forecast" checkpoints, a route-card flag, the banner warning, untinted heatmap cells | e2e `shows missing forecasts as unscored, not safe` | **Fixed**: added the legend entry, the card flag ("unscored, not safe") and popup text. Untinted heatmap cells are explained in the legend. |

## 7. Platform

| Item | Status |
|---|---|
| API keys never reach the frontend or logs | Pass: the live bundle has no key or TomTom URL; the httpx URL logger is silenced; error messages carry no upstream URL |
| One error shape and meaningful HTTP status codes | Pass, except that unknown `/api/*` paths returned Django's HTML 404. **Fixed**: they now return JSON. |
| Production settings (DEBUG off, hosts, CORS limited to the frontend origin, HSTS) | Pass (`manage.py check --deploy`, live headers) |
| Missing TomTom key gives a clear 503 | Pass (`test_tomtom_without_key_is_reported`) |
| Render auto-deploy on push | **Not active**: Render receives no GitHub webhook (the repo is linked by URL). Deploy with the Render CLI or connect Render's GitHub app. |

## 8. Measurements (real TomTom + Open-Meteo, in-process, 2026-10-17)

| Run | TomTom requests | Open-Meteo requests | Weather cells | Time |
|---|---|---|---|---|
| Denver→SLC, 10 mi, cold | 1 (3 real alternatives) | 4 | 95 for 159 checkpoints | 3.8 s (routing 2.6 s) |
| same, weather warm, *before* the route cache | 1 | 0 | 95 cached | 9.8 s (TomTom alone took 9.5 s) |
| same, 0.05° grid (≈ per-checkpoint), for comparison | 1 | 6 | 149 | 9.0 s |
| Seattle→Spokane, 25 mi, cold | 1 | 2 | 33 | 3.6 s |
| same, identical resubmit, **with the route cache** | 0 | 0 | 33 cached | **0.2 s** |
| heatmap after the plan | 0 | 3 | 73 (6 shared with the plan) | 1.3 s |
| heatmap, warm | 0 | 0 | 132 cached | 0.06 s |

The slider triggers no API calls and no map source reloads (e2e and an in-browser measurement).

## 9. Tests executed (final run)

| Suite | Command | Result |
|---|---|---|
| Backend unit, service and API (mocked providers) | `cd backend && uv run pytest` | **204 passed** |
| Backend lint and format | `uv run ruff check . && uv run ruff format --check .` | pass |
| Django deploy check (production env) | `DEBUG=false … manage.py check --deploy` | no issues (4 documented silences) |
| Frontend unit | `npm test` | **14 passed** |
| Frontend lint and types | `npm run lint && npm run typecheck` | pass (strict TS, including e2e) |
| Production build | `npm run build` | pass; the map is a separate lazy chunk |
| End-to-end (Chromium, real UI and MapLibre) | `npm run test:e2e` | **12 passed**, and 24/24 with `--repeat-each=2` |
| Secret scan of the built bundle | grep for the key, api.tomtom.com and open-meteo.com in `dist/` | 0 hits |
| Live smoke test (before this audit's fixes) | browser + curl against the Render deploy | pass |

**Not executed:** the CI workflow with the new e2e job (it needs a push); the Render deploy of these fixes (not pushed or deployed); `docker build` locally (Docker Desktop wouldn't start; Render built the same Dockerfile successfully earlier).

## 10. Remaining limitations and risks

- **These fixes aren't deployed.** The live site still has defects D1–D5 until the changes are pushed **and** deployed (Render gets no push webhook; deploy with the CLI).
- **Free tiers:** Open-Meteo can be overloaded, so cold plans can take 15–30 s; Render's free API sleeps (30–60 s first wake). TomTom's free plan gives 20K routing and 2.5K search requests a month.
- **Detour routes** appear only when TomTom returns fewer than 3 distinct alternatives. They're labeled, but a reviewer may still read the brief as wanting TomTom alternatives only.
- **ETAs are pure drive time** (no hours-of-service breaks), so on very long trips the later checkpoints are forecast for earlier hours than a real driver would arrive.
- **The heatmap is a smoothed grid of real point forecasts** (0.25–1°), not radar. Untinted means no data, which the legend explains.
- **Two ranking additions to the brief's order** (No Travel first, then the coverage gate) are deliberate, documented and tested. The brief's four criteria still apply in their order.
