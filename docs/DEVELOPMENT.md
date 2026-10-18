# How it was built

How the project was approached, the decisions that shaped it, how it was tested, and what was verified against real services. The day-by-day record is in the [project log](project-log/).

## 1. Approach

The grading weights drove the order of work: 40 % routing, weather and risk logic, 40 % map, heatmap and UI smoothness, 15 % code quality, and 5 % documentation. So:

1. **Rules before UI:** the risk table, load rules, ranking and checkpoint math were written first as pure functions, with tests for every edge, before any HTTP or React code.
2. **De-risk the APIs early:** a short spike confirmed that TomTom returns truck routes with per-point travel times, and what the weather data looks like (units, hour stamps, horizon) before the pipeline was designed around it.
3. **Make the map fast by design, then measure it:** rendering choices were checked by counting source reloads and per-move cost.
4. **Ship, then harden:** deploy, run a full audit, fix what it found, and repeat after each production finding.

## 2. Timeline

| Phase | What was built | Notable finding |
|---|---|---|
| Plan and spike | Read the brief, wrote [the plan](project-log/IMPLEMENTATION_PLAN.md), scaffolded both apps, probed TomTom and the first weather API | Free weather APIs were slow per location, so the design snaps checkpoints to the weather model's grid and batches lookups |
| Domain logic | Risk classification, load rules, sampling, ETAs, miles per level, ranking | A test caught `RiskLevel.LOW == 0` being falsy in an `or` expression |
| Providers, services, API | TomTom routing and search, weather client, trip planner, heatmap builder, DRF endpoints with one error shape | — |
| Frontend | Form, route cards, MapLibre layers, heatmap, slider, truck marker | — |
| Map performance | 49 opacity-faded heatmap layers, feature-state highlights | Data-driven paint re-processed the source on every slider frame; now 0 reloads over 40 moves |
| Deployment | Docker image, Render Blueprint, CI, keep-warm workflow | Photon refused connections from Render, so TomTom Search became the production geocoder |
| Audit and hardening | Unforecast miles no longer rank as safe; invalid readings are unknown; timezone-aware departures; route cache; Playwright suite | Two correctness bugs fixed before review |
| Review follow-up | Ranking reduced to exactly the brief's four criteria, with No Travel and missing data as an eligibility constraint; geometric duplicate detection; detour limits | An end-to-end test under load exposed a heatmap layer race, now fixed |
| Weather availability | WeatherAPI.com primary, NWS fallback per value, quota breaker, per-checkpoint sources | Production hit Open-Meteo's free per-IP daily cap on Render's shared IPs |
| UI/UX polish | Responsive single-DOM layout, docked forecast timeline, popup overflow fix, touch targets, accessibility | On phones the popup's top was clipped by up to 94 px; now it auto-anchors inside the map, or docks |

## 3. Key decisions

| Decision | Alternatives considered | Why |
|---|---|---|
| **TomTom truck routing** | OpenRouteService, OSRM | Truck-legal routing that uses the vehicle's weight, alternatives, and travel time per point for real ETAs. ORS limits alternatives to about 100 km routes. |
| **Score the forecast at each checkpoint's ETA**, not at departure | The forecast at departure | The brief's core idea; a long trip crosses weather that hasn't arrived yet when it leaves |
| **Snap weather lookups to a 0.25° grid** | One lookup per checkpoint | Neighbouring checkpoints share a forecast cell anyway, so fewer calls with no loss of resolution, plus a cache shared with the heatmap |
| **No Travel and missing data as eligibility, not ranking criteria** | Extra sort keys | Keeps the ranking exactly the brief's four criteria while still never recommending an unsafe or unassessable route |
| **Missing weather is unknown, never zero** | Treat gaps as calm | A gap that looked like Low would be a false "safe" recommendation |
| **WeatherAPI.com primary, NWS fallback per value** | Open-Meteo (failed on shared IPs), Tomorrow.io (25 requests an hour on the free plan) | Reliable keyed quota, plus a keyless official US source to fill gaps. Details in [WEATHER_PROVIDERS.md](WEATHER_PROVIDERS.md). |
| **49 pre-built heatmap layers cross-faded by opacity** | One layer with a data-driven weight | Opacity changes are free for MapLibre; changing the weight re-processes the source every frame |
| **One DOM for every layout** | Separate mobile and desktop trees | Rotating a tablet or resizing a window never rebuilds the map or loses state |
| **Pure domain layer** | Logic in views or models | The graded rules can be tested exhaustively without a server or network |

## 4. Testing strategy

| Level | Tool | What it proves |
|---|---|---|
| Domain unit | pytest | Every band edge (e.g. 24.9 / 25 / 34.9 / 35 mph; rain 0.0999 / 0.10 / 1.00 / 1.0001), load edges (30,000 vs 30,001 lb), each ranking tie-break, and every route ordering |
| Providers | pytest + respx | Parsing recorded TomTom, WeatherAPI and NWS responses; malformed payloads; timeouts, 5xx errors, rate limits, quota and bad-key responses; bounded retries; keys never echoed in errors |
| Services | pytest with fakes | The trip pipeline end to end: checkpoints, ETAs, detours, eligibility, the weather cache and staleness, field-level fallback with same-hour alignment, source attribution |
| API | DRF test client | Validation messages, error shapes and status codes, and no internals leaked |
| Frontend unit | Vitest | Polyline decoding, heatmap weights and cross-fade, truck position, formatting |
| End-to-end | Playwright (Chromium) | The real UI and map, with `/api/*` mocked by fixtures **exported from the real backend pipeline**, so the frontend is tested against the real API contract. Covers ranking display, the slider, missing data, errors, layout from 320 to 1920 px, popups at all four map edges, touch targets, keyboard use and reduced motion. |
| Visual review | Playwright screenshots | `SCREENSHOTS=<label> npx playwright test screenshots` captures 9 viewports and 5 page states for side-by-side review |

Current totals: **295** backend, **17** frontend unit and **27** end-to-end tests. CI runs all of them on every push.

## 5. Verified against real services

These checks were run against the live services, beyond the mocked tests:

- **TomTom:** truck routes with per-point travel times. 14 corridors were probed while tuning the detour rules.
- **Checkpoint forecasts:** 10 of 10 checkpoints on one live plan matched a direct forecast query for their grid cell and hour.
- **WeatherAPI.com:**
  - Denver → Salt Lake City: all 59 plan cells in 0.9–2.6 s. The heatmap's 119 extra cells took 4.9 s, and NWS filled the 4 cells where WeatherAPI answered for a place more than 20 mi away.
  - A real invalid-key response (HTTP 401, code 2006) correctly paused the provider.
- **NWS:**
  - Grid discovery, the User-Agent requirement, unit conversion, caching, and out-of-coverage handling (a Toronto point is rejected and cached).
  - A full plan served by NWS alone: 59 cells, 118 requests, about 10 s.
- **Production (Render):** after the weather change, a live Denver → Salt Lake City plan returned three routes with 100 % forecast coverage.
- **Browser:** keyboard focus, the phone layout with two-finger map gestures, and checkpoint details docked on a 375 px screen. No console errors.

## 6. Known limitations and next steps

| Limitation | Next step |
|---|---|
| ETAs are pure drive time | Hours-of-service-aware ETAs (break after 8 h, rest after 11 h), which also shifts the forecast hours |
| NWS publishes rain and snow as 6 h totals, so during precipitation those hours stay unknown when NWS is the only source | Add a second hourly provider for gaps outside the WeatherAPI horizon |
| WeatherAPI's free plan forecasts 3 days | The Starter plan gives 7 days, covering the full departure window |
| Free-tier hosting sleeps after 15 minutes | A paid instance, or a keep-warm ping during review |
| Single departure time | "Leave later?": re-score departures at +2, +4 and +6 h and suggest the safest window |
| Manual API types | Generate the TypeScript types from an OpenAPI schema |
