# Progress & Time Log

Budget: at most 16 h over at most 4 days. Plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

| Date | Phase | Hours | Notes |
|---|---|---|---|
| 2026-10-17 | 0: setup and planning | 0.5 | Read the brief, researched providers, scaffolded both apps, wrote the plan |
| 2026-10-17 | 1: API spike | 0.25 | TomTom truck routes plus `progress` confirmed. Open-Meteo overloaded (503, about 0.5 s per location), so switched to `gfs_seamless` on its 0.25° grid |
| 2026-10-17 | 2: domain logic | 0.25 | Risk, load, sampling, ETA, scoring, ranking; 80 tests. Tests caught a `RiskLevel.LOW == 0` falsy bug |
| 2026-10-17 | 3: providers, services, API | 0.25 | Endpoints live against real APIs: plan 20 s cold / 3.5 s warm, heatmap 6 KB gzipped |
| 2026-10-17 | 4–7: frontend | 0.5 | Form, cards, map layers, heatmap, slider, truck marker |
| 2026-10-17 | 8: performance | 0.25 | Found that data-driven paint re-tiled the source every slider frame; now 49 opacity-faded layers plus feature-state, 0 reloads measured. Phone layout fixes |
| 2026-10-17 | 9–11: deploy config, CI, docs | 0.25 | Dockerfile, render.yaml, CI, keep-warm, README, Loom script |
| 2026-10-17 | 9: Render-only hosting | 0.25 | Moved the frontend from Vercel to a Render static site in the same Blueprint. `truck-weather-api`, `spotter-truck-routing` and `spotter-truck-routing-api` were already taken on onrender.com, so the services are named `murtuza-truck-routing(-api)` |

| 2026-10-17 | 9: deploy and live smoke test | 0.25 | Blueprint deployed (the Docker image built on Render in 53 s). Live tests: health, CORS (frontend origin only), HSTS/X-Frame headers, geocode, plan (5–7 s with real weather), heatmap (1.8 s), validation errors. Photon refused connections from Render once, so a TomTom Search fallback was added |

| 2026-10-17 | Audit and hardening | 1.0 | Full audit ([AUDIT.md](AUDIT.md)). Fixed: unforecast miles ranked as safe (P0); NaN or negative weather mis-scored (P0); naive timestamps; malformed TomTom/Open-Meteo payloads; risk miles rounded to 0; unknown `/api/` paths returning HTML. Added a route cache (resubmit 3.6 s → 0.2 s), `meta` accounting, a bounded TomTom retry, Playwright e2e (12), and backend tests up from 131 to 204. Not pushed. |

**Total so far: about 3.75 h of 16 h**

## Remaining

- [x] Deploy the Render Blueprint (API + static site): https://murtuza-truck-routing.onrender.com
- [x] Smoke-test on the live URL: Seattle → Spokane in the browser, with autocomplete, plan, heatmap, slider, metrics and no console errors
- [ ] Optional: connect Render's GitHub app so pushes auto-deploy, run a Blueprint "Manual sync" to apply `GEOCODER_ORDER`, and set the `API_HEALTH_URL` repo variable during review
- [ ] Record the Loom ([LOOM_SCRIPT.md](LOOM_SCRIPT.md)) and add the links to the README
- [ ] Submit the GitHub, hosted and Loom links to Spotter

## Spike findings (resolved)

- [x] TomTom truck routing returned 3 routes for Denver → SLC, each with about 100–200 `progress` entries (`pointIndex`, `distanceInMeters`, `travelTimeInSeconds`)
- [x] Open-Meteo returns `snowfall` in inches with `precipitation_unit=inch`, and gusts are "preceding hour" max values
- [x] A multi-location Open-Meteo request costs about 0.2–0.5 s per location on the free tier today, which is why we snap to the grid, cache and batch
