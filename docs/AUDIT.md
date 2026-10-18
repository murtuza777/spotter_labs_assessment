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
- **Ranking now matches the brief exactly** (review, 2026-10-18): No Travel and missing forecasts moved out of the sort key into an explicit eligibility constraint. See section 11.

## 11. Review follow-up (2026-10-18)

| Item | Finding | Change | Evidence |
|---|---|---|---|
| Ranking vs the brief | The sort key had six criteria (No Travel miles, forecast coverage, then the brief's four), which conflicts with the brief's stated order | The ranking is now exactly Severe → High → avg risk → time. No Travel and missing forecasts are an eligibility constraint applied before ranking: not eligible → never recommended; partial forecasts → provisional at best; No Travel on every route → no recommendation. The UI states the rule and lists each exclusion. | `test_recommend.py` (24 tests: one per tie-breaker, float noise, full ties, all permutations, every eligibility case), e2e `excludes No Travel routes…`, `never presents a No Travel trip as safe` |
| Duplicate detection | The cell-overlap check depended on where samples fell | Geometric similarity: the share of road within 0.3 mi, symmetric minimum. Duplicates are ≥ 95 %. | `test_route_similarity_is_geometric`; live: 14 lanes probed, every one with 3 distinct TomTom routes |
| Detour usefulness | Live probe: 2 of 4 generated detours took 1.55× and 1.74× the fastest drive time, yet would have been accepted | Detours must be ≤ 85 % shared, ≤ 1.4× distance, ≤ 1.5× time, and not an out-and-back spur. The waypoint is shown on the map, and rejected detours are explained in the notice. | `test_unreasonable_detours_are_rejected`, `test_detour_that_repeats…`, `test_out_and_back_spur_is_detected`, e2e `labels a waypoint detour…`, `says so when three meaningful routes cannot be found` |
| Checkpoint weather time and coordinates | — | The API now exposes each checkpoint's queried `weather_cell` | Live check: 10/10 Chicago→Minneapolis checkpoints match a direct Open-Meteo query for that cell and hour exactly; each forecast hour is the ETA rounded up |
| Heatmap missing data | Missing cells were only untinted | Grey dots mark cells with no forecast for the selected hour (opacity-only, so no source reloads) | e2e `shows missing forecasts as unscored, never as calm` (dots at hour 0 and at 30.75 → 31) |
| **Heatmap race (found by e2e under load)** | If the heatmap arrived before the route layers existed, MapLibre rejected all 49 frames ("Cannot add layer … before non-existing layer"), so the heatmap silently didn't appear. Possible in production when the heatmap is served from cache. | The heatmap waits until its anchor layer exists | 45/45 e2e passes with `--repeat-each=3`, with no "Cannot add layer" errors |
| **Weather outage on production (found in the post-deploy smoke test)** | On Render, every Open-Meteo batch failed after retries (it works from other networks, which suggests per-IP limits on Render's shared outbound IPs). All routes had 0 % coverage, yet the fastest was still offered as a "provisional pick", and the log didn't say why the requests failed. | A provisional pick needs at least 50 % forecast coverage; below that, nothing is recommended and the banner says "Weather unavailable: no route can be assessed". Open-Meteo's HTTP status and reason are logged, returned in `meta.weather.errors`, and shown in a notice. | `test_too_little_forecast_is_not_even_a_provisional_pick`, `test_weather_outage_gives_no_recommendation_and_says_why`, `test_open_meteo_failure_reason_is_reported`, e2e `a weather outage gives no recommendation instead of a guess` |
| Risk explanation | The popup listed reasons only for factors above Low | The API returns per-factor readings and levels (threshold level, level after the load rule, and the load-rule text); the popup shows a table and the "worst factor" rule | `test_factors_*`, e2e `checkpoint details explain the risk classification` |
| Route card metrics | Coverage wasn't shown | Cards show distance, drive time, ETA, worst level, Severe mi, High mi, avg risk and forecast coverage, plus an eligibility badge | e2e asserts each label |

**Manual browser test (real TomTom and Open-Meteo, local build):** Denver → SLC planned; the banner shows "Recommended: Route B" with the reason; each card shows all metrics and 100 % forecast; the checkpoint popup shows the factor table and grid cell; Wind metric and slider drag to +18.5 h and +6 h update the time label, truck position ("mile 409 of 526") and the real wind heatmap over the corridor (moderate gusts across Wyoming). On the live site, all 3 demo trips returned 3 TomTom routes and no detour.

**Not reproduced:** the reported "TomTom returned 2 distinct routes, Route C is a waypoint detour" screenshot. None of 14 probed lanes returned fewer than 3 distinct routes today. The detour path is covered by tests with mocked providers, and was exercised live against the TomTom API (`probe_detours`) with the new acceptance rules.

## 12. Production weather availability (2026-10-18)

**Finding:** on Render, Open-Meteo answered every request with HTTP 429 "Daily API request limit exceeded". Its free tier allows 10K calls a day per IP, and Render's free services share outbound IPs. The free tier is also non-commercial only.

**Change:** WeatherAPI.com is the primary provider and the US National Weather Service the fallback. Both sit behind one provider interface and are normalized to one schema (mph, in/hr, the hour ending at each UTC stamp, `None` = unknown). The risk thresholds, load rules and ranking are unchanged. Details: [WEATHER_PROVIDERS.md](WEATHER_PROVIDERS.md).

| Change | Where | Evidence |
|---|---|---|
| Field-level fallback: NWS gets the cells, or the single missing values, WeatherAPI couldn't supply. It fills only the same cell and UTC hour, never replaces a WeatherAPI value, and records the source of every value. | `providers/base.py` (`merge_series`), `services/weather.py` | `test_missing_field_is_filled_from_the_fallback_and_attributed`, `test_fill_needs_the_same_forecast_hour`, `test_complete_primary_data_never_calls_the_fallback`, `test_fallback_can_extend_past_the_primary_horizon` |
| NWS client: `/points` discovery, a descriptive User-Agent, US-only coverage (the InvalidPoint 404 is cached), `/points` cached 24 h and grids 1 h, bounded retries with `Retry-After`, a 1 min pause after persistent 429s, `api.weather.gov` URLs only, the gridpoint polygon checked against the cell, forecasts older than 24 h rejected | `providers/nws.py` | `test_nws_*` (14 tests) |
| NWS normalization: km/h → mph, mm → in. Multi-hour precipitation totals are never spread into hourly rates (zero totals and 1 h intervals only). Probability of precipitation is never used. | `providers/nws.py` | `test_nws_multi_hour_precipitation_totals_are_never_spread_into_hourly_rates`, `test_nws_probability_of_precipitation_is_never_used_as_intensity`; a mutation that spreads totals fails the suite |
| WeatherAPI: quota, key, timeout, malformed-response and missing-hour handling; an answer for a different location is rejected; conservative hour alignment; the key never appears in logs, errors or API responses | `providers/weatherapi.py` | `test_weatherapi_*`, `test_weatherapi_for_another_location_is_not_used` |
| Breaker: a spent quota, a rejected key or a persistent rate limit pauses that provider (shared through the cache), and the notice gives the reason | `services/weather.py` | `test_weatherapi_quota_then_nws_end_to_end`, `test_quota_breaker_skips_provider_until_reset` |
| Per-checkpoint `weather_source`, per-point heatmap `point_sources`, `meta.weather_sources`; the popup shows the source and the forecast panel credits the providers used | `plan_trip.py`, `presenters.py`, `CheckpointPopup.tsx`, `ForecastSlider.tsx`, `lib/weatherSource.ts` | `test_plan_records_each_checkpoint_source_when_a_fallback_fills_gusts`, vitest `describeWeatherSource` |
| A gap no provider can fill leaves those checkpoints unknown, adds a notice, and gives no misleading pick | `plan_trip.py` | `test_a_field_no_provider_has_leaves_checkpoints_unknown_and_unrecommended`, `test_fallback_data_is_scored_with_the_same_rules` |

**Verified live (local machine):**
- NWS served a full Denver → SLC plan (59 cells, 118 requests, 10.3 s) and heatmap (121 cells, 238 requests, 16.8 s). Repeats made 0 requests.
- Toronto got the cached "outside its grids" answer.
- WeatherAPI's real reply to an invalid key (HTTP 401, code 2006) opened the breaker.

**Not verified live:** WeatherAPI with a real key (no key is available here), and production after these changes (nothing pushed or deployed).

## 13. UI/UX polish (2026-10-19)

Frontend only: no API, ranking or risk changes. Screenshots of the before (`SCREENSHOTS=baseline`) and after states were captured at 320, 375, 430, 768, 1024, 1280, 1440 and 1920 px wide, plus 844×390 phone landscape.

| Defect found in the baseline | Change | Evidence |
|---|---|---|
| **Checkpoint popup overflow:** fixed `anchor="bottom"`, so on phones the popup's top sat 94 px above the map (59 px in landscape) and was clipped | No fixed anchor, so MapLibre picks the side that fits, with 12 px edge padding. Maps under 560×520 px dock the same details inside the map: below the point on narrow maps, beside it on short wide ones. A 44 px close button and Escape close it, and focus returns to the list row. | e2e `checkpoint popups stay inside the map near every edge` (left, right, top, bottom); `checkpoint details dock inside the map and close` (375 px) |
| Phones: the legend and timeline covered most of the map; the header sat below the map | Single-column flow below 1024 px: trip, recommendation, map, timeline, routes, checkpoints (`display: contents` + `order`, so the map never remounts). The timeline is docked under the map at every size, and the color key moved into it. | screenshots; `no horizontal page overflow` at 6 widths |
| On a phone, the map trapped page scrolling | Cooperative gestures on touch screens in the single-column layout: one finger scrolls the page, two move the map | verified in the browser pane (375 px mobile emulation) |
| White text on the yellow Moderate badge; Unknown and Low separated only by color on the map | Tinted badges with dark text plus a dot. No forecast is a hollow ring on the map, dashed grey on the route line, hatched in the miles bar, and a dashed badge. | screenshots (partial-forecast and outage states) |
| Controls of 26–30 px; 10–11 px text | Primary controls are 40–48 px (slider hit area 44 px); body text 13–16 px; inputs are 16 px on phones to stop iOS zoom | e2e `primary controls are comfortable touch targets` |
| Long checkpoint list; every metric at the same weight | The form folds into a trip summary after planning; the recommendation leads with a compact metrics line; cards separate trip metrics from ranking metrics; the checkpoint list shows 10 rows plus "Show all" | screenshots |
| A click on a visible checkpoint flew the map away | The map moves only if the checkpoint is off-screen, or hidden behind docked details | asserted in the edge test |
| Route cards contained block elements inside a `<button>`, and their name was the whole card's text | Phrasing-only content plus a concise `aria-label` (status, rank, ranking metrics, limitations) | e2e selectors by role |

**Accessibility:**
- one keyboard focus style;
- the recommendation heading receives focus when a plan arrives;
- `aria-activedescendant` on the place search;
- field errors linked with `aria-describedby`;
- disclosures with visible chevrons;
- `prefers-reduced-motion`: the camera jumps instead of animating, and CSS transitions are off (e2e `honours reduced motion`).

**Not verified:** real iOS/Android devices and truck-mounted displays (only Chromium emulation of touch and mobile viewports), screen readers (semantics checked by role queries, not with NVDA or VoiceOver), and the deployed site (nothing pushed or deployed).
