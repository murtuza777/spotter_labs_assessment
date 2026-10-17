# Loom Walkthrough Script (target 7–8 min, hard limit 5–10)

**Before recording**
- Warm the API: open `/api/health/`, then run one demo trip so the weather cache is hot.
- Find a windy or snowy corridor that day. Open the app, plan a demo trip, switch the heatmap to **Wind** and **Snow**, and drag the slider. If one demo route crosses real weather, use that trip. Otherwise pick a trip across the active weather. Mountain passes (I-80 Wyoming, I-90 Snoqualmie, I-70 Colorado) are the usual suspects.
- Close other tabs, set browser zoom to 100%, and keep the code editor open at `backend/planner/domain/risk.py`.

---

### 1. The problem (0:00–0:45)
- The driver wants the safest of three truck routes, judged by weather **when the truck gets there**, load weight, and drive time.
- Mention the stack in one sentence: React + MapLibre on the frontend, Django on the backend, TomTom truck routing, Open-Meteo forecasts.

### 2. Live demo (0:45–3:30)
1. Click a demo trip (or type places to show the autocomplete). Point out the departure time, the load, the **10/25/50 mi** checkpoint toggle, and the wind-rule option.
2. Submit. While it loads, mention the progress messages and that the first plan is slower on the free weather tier.
3. **Recommendation banner:** read the reason out loud. It compares the pick against *every* other route, and notes the ranking order.
4. **Route cards:** distance, drive time, arrival, worst level, the stacked miles-by-level bar, average risk.
5. **Map:** click another route to select it; hover a checkpoint to show the popup with ETA, gusts, sustained wind, rain, snow and the **reason** text. Show a load escalation if one exists, or raise the load to 45,000 lb and replan to make one appear.
6. **Heatmap and slider:** press play. The truck marker moves with the forecast, and checkpoints get a ring as the truck reaches them. Switch Risk → Wind → Snow. *"The truck reaches mile 200 at 9 pm, so that's the forecast hour we score, not the departure hour."*

### 3. How the logic works (3:30–5:45)
Show the code briefly.
- `domain/risk.py`: the bands are half-open, and a value on a shared edge goes to the higher level. Load rules only change wind, and checkpoint risk is the worst of the three factors.
- `domain/timebucket.py`: Open-Meteo stamps each hour's values at its end, so the ETA rounds **up** to the next hour.
- `domain/scoring.py`: each checkpoint owns the miles from midpoint to midpoint, so the miles add up exactly to the route length.
- `domain/recommend.py`: the ranking order. **No Travel goes first**, and say why. Rounding means float noise counts as a tie.
- `services/plan_trip.py`: ETAs come from TomTom's per-point travel times. If TomTom returns fewer than 3 routes, detour waypoints fill the gap.
- Run `uv run pytest -q` → 125 passed. Scroll `test_risk.py` to show the edge cases.

### 4. Map performance (5:45–7:00)
- Everything on the map is WebGL. Only the truck and the two endpoints are DOM markers.
- **Key point:** changing a data-driven paint property makes MapLibre re-tile the source on every frame. So the heatmap is 49 layers, one per hour, and the slider only cross-fades opacity. The near-ETA checkpoint rings use feature-state. Measured: 0 source reloads over 40 slider moves.
- Heatmap radius and intensity come from the grid spacing, so it renders as a smooth field at every zoom.
- The map code is lazy-loaded, geometry is simplified and encoded on the server, and responses are gzipped.

### 5. Trade-offs and next steps (7:00–7:45)
- Free weather tier latency, and how caching and grid snapping keep it manageable.
- No hours-of-service breaks yet. Next: HOS-aware ETAs, and "leave later?" suggestions.
- Close: *"Correctness first: every rule interpretation is written down in the README and pinned by a test."*
