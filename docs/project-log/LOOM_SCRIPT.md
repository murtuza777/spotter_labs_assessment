# Loom Walkthrough Script (target 7–8 min, hard limit 5–10)

**Before recording**
- **Warm the API:** open https://murtuza-truck-routing-api.onrender.com/api/health/, then plan one demo trip so the routing and weather caches are hot. A cold free-tier instance takes 30–60 s to wake.
- **Pick a trip with weather:** open the app, plan a demo trip, switch the timeline to **Wind** and **Snow**, and drag the slider. If one demo route crosses real weather, use that trip. Otherwise plan a trip across the active weather; mountain passes (I-80 Wyoming, I-90 Snoqualmie, I-70 Colorado) are the usual suspects.
- **Set up the screen:** close other tabs, set browser zoom to 100 %, and keep the editor open at `backend/planner/domain/risk.py`. For the phone segment, use the browser's device toolbar at 375 px, or a real phone.

---

### 1. The problem (0:00–0:40)
- The driver wants the safest of three truck routes, judged by the weather **when the truck gets to each point**, the load weight, and drive time.
- **Stack, in one sentence:** React + MapLibre (WebGL) on the frontend; Django + DRF on the backend; TomTom truck routing; WeatherAPI.com forecasts with the US National Weather Service as fallback. It all runs on Render.

### 2. Live demo, desktop (0:40–3:30)
1. **Trip form:** click a demo trip, or type a place to show the autocomplete. Point out the departure time, the load, the **10 / 25 / 50 mi** checkpoint spacing, and the gust-or-sustained wind rule.
2. **Submit:** the progress messages show each step. The form then folds into a **trip summary**, so the answer is at the top.
3. **Recommendation:** read the banner out loud. It shows the picked route's distance, drive time, arrival, Severe and High miles and forecast coverage, and why it beats *every* other route. Open **How routes are ranked**: exactly Severe miles → High miles → average risk → drive time. No Travel is a separate safety rule: such a route is never recommended.
4. **Compare routes:** each card has the same metrics, an eligibility badge and a miles-by-level bar. Click another card: the map highlights it with no new request.
5. **Checkpoints:** click a checkpoint on the map, or in the list. The popup shows each factor's forecast and level, the load rule if it applied, the forecast hour and grid cell, and the **weather source**. If the load rule matters, raise the load to 45,000 lb and replan to show *"Severe raised to No Travel"*.
6. **Timeline under the map:** press play. The truck marker moves, and checkpoints get a ring as the truck reaches them. Switch Risk → Wind → Snow; the color key shows each band's range. *"The truck reaches mile 200 at 9 pm, so that's the forecast hour we score, not the departure hour."* Open **How to read the map**: the heatmap is smoothed between point forecasts, and grey or hollow means no forecast, never "calm".

### 3. Phone and tablet (3:30–4:15)
- At 375 px the page reorders itself: trip, recommendation, map and timeline, routes, checkpoints. Nothing overflows, and the controls are 40–48 px.
- One finger scrolls the page and two move the map, so the map never traps scrolling.
- Tap a checkpoint in the list: the page scrolls back to the map, and the details dock inside it, so they're never cut off.

### 4. How the logic works (4:15–6:15)
Show the code briefly.
- **`domain/risk.py`:** bands are half-open, so a value on a shared edge goes to the higher level. Load rules only change wind, and checkpoint risk is the worst of the three factors.
- **`domain/timebucket.py`:** every value is normalized to the hour **ending** at its timestamp, so the ETA rounds up to the next hour.
- **`domain/scoring.py`:** each checkpoint owns the miles from the midpoint before it to the midpoint after it, so the miles add up exactly to the route length.
- **`domain/recommend.py`:** the four criteria and nothing else. No Travel and missing forecasts are eligibility constraints: a route missing forecasts can only be a provisional pick, and below 50 % coverage nothing is recommended.
- **`services/weather.py`:**
  - forecasts are cached per 0.25° grid cell;
  - WeatherAPI goes first, and NWS fills only the gaps, for the same cell and hour;
  - every value records its source;
  - a spent quota pauses that provider instead of being retried.
  
  *"Production originally hit Open-Meteo's free per-IP daily cap on Render's shared IPs; this chain is the fix."*
- **Tests:** `uv run pytest -q` passes 295 tests. Then run `npm run test:e2e` (27 passed in Chromium, including popups at all four map edges and no overflow from 320 to 1920 px). Scroll `test_risk.py` to show the edge cases.

### 5. Map performance (6:15–7:15)
- Everything on the map is WebGL. Only the truck and the two endpoints are DOM markers.
- **Key point:** changing a data-driven paint property makes MapLibre re-tile the source on every frame. So the heatmap is 49 layers, one per hour, and the slider only cross-fades opacity. The near-ETA rings use feature-state. Measured: 0 source reloads over 40 slider moves, and the slider makes no API calls.
- The map code is lazy-loaded; geometry is simplified and encoded on the server; responses are gzipped.

### 6. Trade-offs and next steps (7:15–7:50)
- **Weather limits:** NWS gives rain and snow only as 6 h totals. Those hours stay "No forecast" rather than being guessed, so with NWS alone a stormy trip may get only a provisional pick.
- **Next:** hours-of-service-aware ETAs, and "leave later?" suggestions.
- **Close:** *"Correctness first: every rule interpretation is written down in the README and pinned by a test."*
