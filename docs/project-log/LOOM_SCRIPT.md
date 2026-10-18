# Loom walkthrough script

**Target: about 8 minutes. Hard limit: 5–10 minutes.**

The order follows the grading weights: routing, weather and risk logic (40 %) and the map, heatmap and UI (40 %) get most of the time, then code quality (15 %) and docs (5 %). Each segment lists what to **show** and what to **say**. Read the lines in your own words rather than word for word.

---

## Before recording (10 minutes)

- [ ] **Wake the API:** open https://murtuza-truck-routing-api.onrender.com/api/health/ and wait for `{"status":"ok"}`. A cold free-tier server takes 30–60 s.
- [ ] **Warm the caches:** open https://murtuza-truck-routing.onrender.com and plan **Denver → Salt Lake City** once, so the recording isn't waiting on first-time routing and weather.
- [ ] **Confirm the weather source:** click a checkpoint and check it says *Weather source: WeatherAPI.com*. If it says *National Weather Service*, the Render key isn't set; that's fine, just say so in segment 4.
- [ ] **Find some weather:** plan the other demo trips (Seattle → Spokane, Chicago → Minneapolis), switch the timeline to **Wind** and **Snow**, and drag the slider. Use whichever trip shows real weather. If none does, try a mountain corridor such as I-80 through Wyoming or I-70 through Colorado.
- [ ] **Prepare a load-rule example:** if a route has gusts of 45 mph or more, note it; segment 3 raises the load to show the rule. If no wind is strong enough today, explain the rule from the unit tests instead.
- [ ] **Browser:** one window at 100 % zoom, other tabs closed, DevTools ready for the phone view (Ctrl+Shift+M).
- [ ] **Editor:** open these files in tabs: `backend/planner/domain/risk.py`, `domain/recommend.py`, `services/weather.py`, `frontend/src/features/map/HeatmapLayer.tsx`, and `README.md`.
- [ ] **Terminal:** in `backend/`, have `uv run pytest -q` ready to run. It takes about 20 s.

---

## 1. Introduction (0:00–0:40)

**Show:** the live app, with no trip planned yet.

**Say:**
> "Hi, I'm Murtuza. This is my Weather-Aware Truck Routing app for the Spotter AI assessment. A driver enters an origin, a destination, a departure time and the load weight. The app finds three truck routes and checks the weather at regular checkpoints. The key idea is that each checkpoint is scored with the forecast **for the hour the truck actually gets there**, not the hour it leaves. Then it applies the assessment's wind, rain, snow and load rules and recommends the safest route.
>
> The frontend is React with MapLibre for WebGL maps. The backend is Django REST Framework. Routes come from TomTom's truck routing, and forecasts come from WeatherAPI.com, with the US National Weather Service as a fallback. Both parts are deployed on Render."

## 2. Planning a trip (0:40–2:00)

**Show:** the trip form.
1. Type "Denv" in Origin to show the autocomplete, then click the **Denver → Salt Lake City** demo.
2. Point out the departure time (with its timezone), the load in pounds, the **10 / 25 / 50 mi** checkpoint spacing, and the **wind rule** (gusts or sustained).
3. Click **Find the safest route**.

**Say:**
> "These are the four inputs from the brief, plus the checkpoint spacing the brief asks for, 10, 25 or 50 miles. The departure always carries a timezone, because a wrong guess there would shift every forecast hour. The progress messages show the steps: three truck routes from TomTom, checkpoints with arrival times, and the forecast for each checkpoint's arrival hour."

**Show:** the result. The form folds into a trip summary.

**Say:**
> "Once the plan is ready, the form folds into a summary, so the answer is the first thing you see."

## 3. The recommendation and the rules (2:00–3:40)

**Show:** the recommendation banner. Read the compact line: distance, drive time, arrival, Severe miles, High miles and forecast coverage. Then read the reason sentence.

**Say:**
> "The banner says which route to take, and why. It compares the pick with every other route on the first criterion that separates them. The ranking is exactly the brief's order: fewest Severe miles, then fewest High miles, then lowest average risk, then shortest drive time."

**Show:** open **How routes are ranked**.

**Say:**
> "There's one safety rule on top of the ranking, kept separate so the ranking stays exactly the brief's. A route with any No Travel miles is never recommended. And if a route is missing forecasts, it can't be called safe, so it can only be a clearly labeled provisional pick."

**Show:** the **Compare routes** cards. Point out that each has the same metrics, a status badge and a miles-by-level bar. Click another card; the map highlights it.

**Say:**
> "Every route shows the same comparable numbers, and the badge says if a route is excluded and why. Switching routes is instant: no new request, just state in the browser."

**Show:** click a checkpoint on the map, or a row in the checkpoint list.

**Say:**
> "Each checkpoint shows the reading and the level for gusts, rain and snow. The checkpoint's risk is the worst of the three. Here's the forecast hour it used: the ETA rounded up, because each forecast value covers the hour ending at its timestamp. And here's where the weather came from."

**Optional, if strong wind is present:** click **Edit trip**, set the load to **45,000 lb**, and plan again.
> "With more than 30,000 pounds, gusts of 45 to 54 mph go from Severe to No Travel. With more than 40,000 pounds, 35 to 44 mph goes from High to Severe. The details say exactly which rule fired."

## 4. Weather through time, and the map (3:40–5:00)

**Show:** the forecast timeline docked under the map. Press **play**, then pause and drag the slider.

**Say:**
> "The timeline covers 0 to 48 hours from departure. As it plays, the truck moves along the selected route at its real pace, and checkpoints get a ring as the truck reaches them. The heatmap shows the forecast across the whole trip corridor at that moment."

**Show:** switch **Risk → Wind → Snow**. Point at the color key and its value ranges.

**Say:**
> "Every variable uses the same five risk colors, so the key always means the same thing, and it shows each band's range. Missing data is never painted as calm. Grey dots on the heatmap, hollow checkpoints and dashed grey route stretches all mean *no forecast*, and those miles aren't scored."

**Say, about the weather source:**
> "On the backend, every forecast is converted to the same units and hourly convention. WeatherAPI.com goes first. If it fails, hits its quota, or leaves a value missing, the National Weather Service fills just that gap, for the same place and hour. Every value records its source. I added this after production hit Open-Meteo's free per-IP limit on Render's shared IPs."

## 5. Phone and tablet (5:00–5:40)

**Show:** DevTools device mode at 375 px, reloaded. Plan the trip.

**Say:**
> "It isn't a shrunken desktop. On a phone the page reorders: trip, answer, map and timeline, routes, then checkpoints. Controls are at least 40 pixels for touch. One finger scrolls the page and two fingers move the map, so the map never traps scrolling."

**Show:** scroll down, tap a checkpoint row. The page scrolls back to the map, and the details dock inside it.

**Say:**
> "On small screens the details dock inside the map instead of floating, so they never get cut off at the edge. I tested popups near all four map edges, and widths from 320 to 1920 pixels."

## 6. Code walkthrough (5:40–7:20)

**Show:** the editor, quickly. Spend 15–20 s per file.

1. **`domain/risk.py`**
   > "All the rules live in a pure-Python domain layer, with no Django and no network. The bands include the lower bound, so a value exactly on an edge goes to the higher level. The brief writes No Travel rain as *over* 1.00, so exactly 1.00 stays Severe. The load rules change only wind."
2. **`domain/recommend.py`**
   > "This is the ranking: four criteria and nothing else. No Travel and missing forecasts are an eligibility step before it. Values are compared at fixed precision, so float noise can't change the winner."
3. **`services/weather.py`**
   > "Checkpoints snap to a 0.25-degree weather grid, so neighbours share one lookup, and the cache is shared with the heatmap. This is the provider chain: the fallback only fills gaps, and a provider that runs out of quota is paused, not hammered with retries."
4. **`frontend/.../HeatmapLayer.tsx`**
   > "For smoothness: changing a data-driven paint property makes MapLibre re-process the data every frame. So I build 49 heatmap layers once, one per hour, and the slider only cross-fades opacity. I measured zero source reloads over 40 slider moves. Moving the slider never calls the API."

**Show:** run `uv run pytest -q` in the terminal; it shows **295 passed**.

**Say:**
> "There are 295 backend tests, covering every band edge, every load edge, every ranking tie-break, and the weather fallbacks. On the frontend, 27 Playwright tests drive the real map in Chromium, using fixtures exported from the real backend, plus 17 unit tests. CI runs all of them on every push."

## 7. Docs and wrap-up (7:20–8:10)

**Show:** the README on GitHub. Scroll past the evaluation guide and the requirements table, then the docs index.

**Say:**
> "The README has a five-minute evaluation guide and a table mapping each requirement to the code and tests. The docs cover the architecture, the API, the risk model, with every interpretation written down, and how it was built.
>
> Known limits: ETAs are pure drive time, without hours-of-service breaks, and the NWS fallback only gives rain and snow as 6-hour totals, so those hours show as *no forecast* rather than a guess. Next, I'd add hours-of-service-aware ETAs and a 'leave later?' suggestion that re-scores later departures.
>
> My priority was correctness first: every rule is tested at its edges, and the app never shows an unknown or unsafe route as safe. Thanks for watching."

---

## If something goes wrong while recording

| Problem | What to do |
|---|---|
| The API is asleep (slow first plan) | Keep talking over the progress messages (segment 2 covers them), or pause the recording and resume after it loads |
| No interesting weather today | Show the **How to read the map** note and a checkpoint table, and explain the load rule using `test_risk.py` |
| A checkpoint says "National Weather Service" | Explain the fallback; it shows the chain working |
| You're running long | Shorten segment 5 to one sentence and skip the optional load replan |

## Checklist after recording

- [ ] The length is between 5 and 10 minutes.
- [ ] Every requirement appears: inputs, three routes, checkpoint spacing at the ETA, risk and load rules, ranking, the map with routes, checkpoints, risk and ETAs, and the heatmap with the 0–48 h slider.
- [ ] Paste the Loom URL into `README.md` (the "Walkthrough video" row) and [SUBMISSION.md](SUBMISSION.md), then commit and push.
