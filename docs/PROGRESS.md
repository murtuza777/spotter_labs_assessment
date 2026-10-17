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
| 2026-10-17 | 9–11: deploy config, CI, docs | 0.25 | Dockerfile, render.yaml, vercel.json, CI, keep-warm, README, Loom script |

**Total so far: about 2.25 h of 16 h**

## Remaining

- [ ] Deploy: Render (API) and Vercel (frontend), set `CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL`, and the `API_HEALTH_URL` repo variable
- [ ] Smoke-test the 3 demo trips on the live URL
- [ ] Record the Loom ([LOOM_SCRIPT.md](LOOM_SCRIPT.md)) and add the links to the README
- [ ] Submit the GitHub, hosted and Loom links to Spotter

## Spike findings (resolved)

- [x] TomTom truck routing returned 3 routes for Denver → SLC, each with about 100–200 `progress` entries (`pointIndex`, `distanceInMeters`, `travelTimeInSeconds`)
- [x] Open-Meteo returns `snowfall` in inches with `precipitation_unit=inch`, and gusts are "preceding hour" max values
- [x] A multi-location Open-Meteo request costs about 0.2–0.5 s per location on the free tier today, which is why we snap to the grid, cache and batch
