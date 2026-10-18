# Weather providers

The app gets forecasts from **WeatherAPI.com** (the primary) and the **US National Weather Service** (the fallback). Both are normalized into one schema, so the risk engine, the ranking, the API and the UI see the same data whichever provider supplied it.

**Why this setup:** production first used Open-Meteo's free API. On Render it failed with HTTP 429 "Daily API request limit exceeded", because the free tier caps each IP at 10,000 calls a day and Render's free services share outbound IPs with other tenants. Open-Meteo is still available as an optional extra provider (see [Configuration](#configuration)).

## The normalized schema

[`providers/base.py`](../backend/planner/providers/base.py) defines `HourlySeries`, the format every provider converts into:

- **Readings:** for each cell and each **hour ending at a UTC stamp**: sustained wind and gusts in **mph**, rain and snow in **in/hr**.
- **Missing values:** anything absent, non-numeric, negative or NaN is `None`, which means **unknown, never zero**. A checkpoint whose hour is missing any of the four values is shown as "No forecast" and isn't scored.
- **Sources:** every value records the provider that supplied it.

[`providers/weatherapi.py`](../backend/planner/providers/weatherapi.py) and [`providers/nws.py`](../backend/planner/providers/nws.py) handle all the HTTP, parsing and unit conversion. [`services/weather.py`](../backend/planner/services/weather.py) handles caching and the fallback order. The risk thresholds, load rules and ranking are unchanged.

## Provider selection and fallback

For each request, the service works through the 0.25° grid cells that the checkpoints (or heatmap points) fall in, over the forecast hours needed:

1. **Cache.** A cached series is used if it is fresh (60 min), spans the window, and either has no gaps in it or the whole chain was already asked about those gaps. So known gaps aren't refetched on every request until the TTL runs out.
2. **WeatherAPI.com** gets every cell that isn't cached.
3. **NWS** gets every cell where WeatherAPI:
   - failed: an error, timeout, 5xx, rejected key, spent quota, malformed response, or an answer for a different location;
   - is missing any of the four values for any hour of the window: a missing field, a missing hour, or an hour past its forecast horizon.
4. **NWS fills gaps only:**
   - same cell, same UTC hour;
   - never replacing a value WeatherAPI supplied;
   - only with values that passed validation (below).
   
   If WeatherAPI returned nothing for a cell, NWS supplies the whole cell.
5. **Whatever is still missing stays unknown.**
   - Those checkpoints are "No forecast", and a notice says why.
   - A route that isn't fully forecast can at best be a **provisional** pick; with less than 50 % coverage, **nothing is recommended**.
   - No Travel routes are never recommended, as before.

| Trigger | What happens |
|---|---|
| WeatherAPI quota spent (HTTP 403, code 2007) | No retry; unsent requests are cancelled. WeatherAPI is skipped until the 1st of next month, and NWS serves. |
| WeatherAPI key missing, invalid or disabled (1002, 2006, 2008, 2009) | No retry. Skipped for 1 h, and NWS serves. Verified live: an invalid key gets HTTP 401, code 2006. |
| WeatherAPI timeout or 5xx | 1 retry with backoff, then NWS |
| WeatherAPI malformed JSON, no hourly data, or the wrong location | That cell goes to NWS |
| WeatherAPI missing a value or an hour | NWS fills that value, for that hour only |
| NWS 429 or 5xx, or a timeout | 2 retries with backoff, honouring `Retry-After` (up to 5 s). A 429 that persists pauses NWS for 1 minute. |
| Location outside NWS coverage | Not sent to NWS. Edge cases get a `/points` 404 "InvalidPoint", which is cached for a day. |
| Both providers fail | Unknown; the notice lists each provider's reason |

- **Where the breaker lives:** in the Django cache, which the production file cache shares across gunicorn workers. The skip notice carries the reason, e.g. `weatherapi: skipped, paused until 2026-10-18T18:24+00:00 (HTTP 401 (code 2006): API key is invalid.)`.
- **Where sources are recorded:**
  - each checkpoint's `weather_source`, e.g. `{"wind_mph": "weatherapi", "gust_mph": "nws", …}`;
  - each heatmap point's `point_sources` entry, e.g. `"weatherapi+nws"`;
  - `meta.weather_sources` on every response.
  
  The checkpoint popup shows the source, e.g. "source: WeatherAPI.com; gusts from National Weather Service", and the forecast panel credits the providers used.

## What each provider can supply

Checked against each provider's docs and the live APIs on 2026-10-18.

| Need | WeatherAPI.com (`forecast.json`) | NWS (`/gridpoints/{wfo}/{x},{y}`) |
|---|---|---|
| Sustained wind | `wind_mph`, hourly | `windSpeed` in km/h, converted to mph. A value is held over a 1–13 h run, and applies to each hour of it. |
| Gusts | `gust_mph`, hourly | `windGust` in km/h, converted to mph, held the same way |
| Rain intensity | `precip_in`, an hourly amount with **no rain/snow split**. Whether it includes melted snow isn't documented, so **all of it is scored as rain** (this can only overstate rain). | `quantitativePrecipitation` in mm: a **total over a 6 h period** (sometimes 4 h), not hourly. See below. |
| Snow intensity | `snow_cm`, hourly, converted to inches | `snowfallAmount` in mm of snow: a **6 h total**. See below. |
| Hour alignment | The docs don't say whether a value covers the hour before or after its stamp, so the normalized hour ending at H takes the **worse** of the stamps H−1 and H | Explicit `start/duration` intervals. Wind takes the worse of H−1 and H, like WeatherAPI; amounts use the interval that contains the hour. |
| Horizon | Free plan 3 days; Starter 7 days | About 7 days |
| Coverage | Worldwide | US states and territories: CONUS, Alaska, Hawaii, Puerto Rico and the USVI, Guam |
| Limits | Free plan 100K calls/month; Starter $7 for 3M; one location per call | No key. The limit isn't published; the docs say to retry after about 5 s. A User-Agent identifying the app is required. |
| Validation | Hour-boundary timestamps; the `location` answered for must be within 20 mi of the cell | Known units only; hour-boundary times; `updateTime` within 24 h; the gridpoint polygon within 3 mi of the cell; grid URLs only on `api.weather.gov` |

**Why NWS rain and snow are often unknown:** the schema needs in/hr, but NWS publishes totals over 6 hours. A 6 h total says nothing about any single hour; 0.5 in could have fallen in one hour or spread over six. So an NWS hour gets a rain or snow value only:

- **when its interval is exactly 1 h long** (rare): that total is the hourly amount;
- **when the interval's total is exactly 0:** no precipitation fell in any of its hours, so every hour is exactly 0.

Any measurable 6 h total leaves those hours unknown. Spreading a total evenly would understate the peak, and treating the total as one hour's amount would overstate it, so neither is done.

**Never used as intensity:** probability of precipitation (from either provider), the NWS hourly text forecast (`/forecast/hourly`, which has no gusts and no amounts), and daily totals.

### Variables a provider can't reliably supply

- **NWS: hourly rain and snow intensity during any measurable precipitation.** NWS can confirm dry hours and wind, but when it's the only source during a storm, the wet hours stay unknown. Measured live: 24 unknown rain-hours for one Colorado mountain cell on 2026-10-19, and 15 of 121 heatmap cells with gaps.
- **WeatherAPI: the rain/snow split and the hour semantics.** Both are handled conservatively, as described above. The free plan also stops at 3 days, so later hours depend on NWS.
- **Both: outside the US, only WeatherAPI is available.** If it fails there, those miles are unknown.
- **Not modelled by either:** freezing rain and ice. The brief's rules don't include them.

## Performance and API usage

Measured live on 2026-10-18, Denver → Salt Lake City, 3 TomTom routes, 25 mi checkpoints.

| Lookup | Cells | WeatherAPI requests | NWS requests (cold) | NWS latency (measured) |
|---|---|---|---|---|
| Plan | 59 | 59 | 118 (`/points` + gridpoint for each cell) | 10.3 s |
| Heatmap, after the plan | 121 new (11 cached) | 121 | 238 | 16.8 s |
| Same trip again within 60 min | 0 | 0 | 0 | plan 0.37 s, heatmap 0.10 s in total |
| Moving the slider, or switching metric or route | — | 0 | 0 | — |

- **Normal operation:** WeatherAPI serves everything, and NWS is called only for gaps. A cold trip with plan and heatmap costs about **180 WeatherAPI requests** at 25 mi spacing, or 205 at 10 mi. The free plan's 100K/month covers about **500–550 cold trips a month**.
  - **Measured live (2026-10-19, real key):** a cold plan's 59 cells took 0.9–2.6 s, and the heatmap's 119 extra cells 4.9 s, at 6 parallel requests.
- **When NWS serves a whole trip** (WeatherAPI down or unconfigured): about 360 requests and 25–30 s cold. Repeats are cached.
  - `/points` metadata is cached for 24 h, matching its `max-age`.
  - Gridpoint forecasts are cached for 1 h, matching their `max-age` (each is 200–260 KB raw; only the normalized series is cached).
- **Deduplication:**
  - cells are deduplicated within each request;
  - gridpoints are deduplicated if two cells share one;
  - one cached series per cell serves every checkpoint hour in it, plus the heatmap.
- **Timeouts:** every request has a timeout (`HTTP_TIMEOUT_SECONDS`, default 30 s; connect 5 s). Retries are bounded, and quota and key errors are never retried.
- **Concurrency:** WeatherAPI uses 6 parallel requests, NWS 6.

## Observability

All logs leave out keys. WeatherAPI's key is scrubbed from error text; NWS has no key.

- **Per WeatherAPI call:** `weather provider=weatherapi cells=… ok=… requests=… statuses={…} ms=…`
- **Per NWS call:** `weather provider=nws cells=… ok=… outside_us=… requests=… statuses={…} cache_hits={'point': n, 'grid': n} ms=…`
- **Per lookup:** `weather cells= cached= fetched= failed= incomplete= ms= providers=[(name, requests, statuses, cells_ok, cells_used, skipped)]`
- **Breaker:** `weather provider=<name> breaker open until <time> (<reason>)` at WARNING level
- **In responses:** `meta.weather` repeats the per-provider counts, and `meta.weather.errors` lists the reasons, prefixed by provider.

## Configuration

Settings for the API service. Locally they go in `backend/.env`; on Render, in the service's Environment settings.

| Variable | Default | Notes |
|---|---|---|
| `WEATHERAPI_KEY` | (empty) | **Secret.** The primary provider. Without it the chain is NWS only (a warning is logged). |
| `WEATHER_PROVIDERS` | `weatherapi,nws` | Provider order. Add `open-meteo` to use it as well. |
| `WEATHERAPI_DAYS` | `3` | Forecast days your WeatherAPI plan allows: Free 3, Starter 7 |
| `NWS_USER_AGENT` | `truck-weather-routing/1.0 (+https://github.com/murtuza777/spotter_labs_assessment)` | NWS asks for the app's name and a contact. Override it to name your own contact. |
| `NWS_MAX_WORKERS`, `NWS_POINT_TTL_S`, `NWS_GRID_TTL_S`, `NWS_MAX_AGE_H` | `6`, `86400`, `3600`, `24` | Tuning: parallel requests, cache lifetimes, and the oldest forecast accepted |
| `OPEN_METEO_API_KEY` | (empty) | Only if `open-meteo` is in `WEATHER_PROVIDERS` |

### Render setup

Nothing in this change has been deployed. The live site keeps its current configuration until these steps are done.

1. **Get a WeatherAPI key:** create a free account at https://www.weatherapi.com/signup.aspx; the key is on the dashboard.
2. **Add the key:** Render Dashboard → `murtuza-truck-routing-api` → **Environment** → add `WEATHERAPI_KEY` (secret) and save.
   - [`render.yaml`](../render.yaml) already declares `WEATHER_PROVIDERS=weatherapi,nws`, `WEATHERAPI_DAYS=3` and `WEATHERAPI_KEY` (`sync: false`).
   - A Blueprint sync never fills in secrets, so the key must be entered by hand.
   - The Blueprint values only apply after a sync, so either sync the Blueprint (Blueprints → Manual sync) or add `WEATHER_PROVIDERS=weatherapi,nws` by hand too. If neither is done, the code default (`weatherapi,nws`) applies once the new code is deployed.
3. **Deploy the new code**, since pushes don't auto-deploy here: commit and push, then
   `render deploys create srv-db9p2s5g1s2s739hbdag --commit <sha> --wait --confirm` for the API, and the same for the static site `srv-db9p2s5g1s2s739hbda0`.
4. **Verify:**
   - `curl https://murtuza-truck-routing-api.onrender.com/api/health/` should return OK.
   - Plan a demo trip in the app. The response's `meta.weather.providers[0]` should be `{"name": "weatherapi", "statuses": {"200": N}, …}`, and `meta.weather_sources` should include `weatherapi`.
   - The checkpoint popups should say "source: WeatherAPI.com", and the forecast panel should show "Powered by WeatherAPI.com".
   - The Render logs should show `weather provider=weatherapi … statuses={'200': …}` and no `breaker open` warnings.
   - **To check the fallback:** temporarily set `WEATHERAPI_KEY` to a wrong value. Notices should then say "Some forecasts came from the fallback provider the National Weather Service", checkpoints should show "source: National Weather Service", and the logs should show `breaker open … (HTTP 401 (code 2006) …)`. Restore the key afterwards.

**Migration:**
- **Database:** none; the app has no models.
- **Cache:** keys moved to `wx:v3:<chain>:…`, which includes the provider chain, so changing the chain never serves the old chain's data. `/tmp` is cleared on deploy anyway.
- **Rollback:** set `WEATHER_PROVIDERS=open-meteo` (the previous behaviour), or redeploy the previous commit.

## Verification status

- **Verified live (2026-10-18, local machine):**
  - NWS discovery, the User-Agent, unit conversion, the 6 h total rule, caching (repeats made 0 requests), out-of-coverage handling (Toronto: 404, cached) and the over-precise coordinate redirect;
  - a full Denver → SLC plan and heatmap served by NWS;
  - WeatherAPI's real response to an invalid key (HTTP 401, code 2006), which opens the breaker and hands every cell to NWS.
- **Verified live with a real WeatherAPI key (2026-10-19, local machine):**
  - a cold Denver → SLC plan: 59 of 59 cells served by WeatherAPI, all HTTP 200, with every checkpoint sourced from it;
  - the heatmap: 115 of 119 cells from WeatherAPI. For the other 4, WeatherAPI answered for a named place more than 20 mi from the cell; the location check rejected them and NWS filled them, leaving 0 unknown cells;
  - repeats within 60 min: no weather calls;
  - finding: for a coordinate query, WeatherAPI returns the **nearest named place's** coordinates (39.75, −105.00 came back as Denver, 39.739, −104.984), not the exact point. The 20 mi check is what keeps sparse areas honest.
- **Verified in production (2026-10-19):** after deploying, a live plan returned 3 routes with 100 % coverage. No key was set on Render yet, so NWS served it (118 requests, all 200).
- **Mocked tests only:** WeatherAPI quota, timeouts and malformed responses; NWS rate limits and 5xx errors. See `planner/tests/test_weather_providers.py` and `planner/tests/test_nws_fallback.py`.
- **Still unconfirmed:** WeatherAPI's exact hour semantics and whether `precip_in` includes melted snow. Both are handled conservatively, as described above.

## Risks

- **No WeatherAPI key, or WeatherAPI down:** NWS alone is slow when cold (about 25–30 s for a plan and its heatmap), covers only the US, and leaves the wet hours unknown. The UI handles all of this correctly (No forecast, provisional, or no recommendation), but recommendations become rarer in stormy weather.
- **WeatherAPI quota:** about 500 cold trips a month on the free plan. Starter ($7) raises that to about 16,000 trips and extends the horizon to 7 days.
- **NWS reliability:** NWS sometimes serves stale grids, which are rejected after 24 h, and has short 5xx outages. Its rate limit isn't published, so bursts may hit a 429, which pauses NWS for a minute.
- **Mixed providers:** neighbouring cells, or values within one cell, can come from different models. The source is shown, and the notice says when the fallback was used.

## Evaluated and not used

- **Tomorrow.io:** its free plan allows 500 requests a day and 25 an hour, one location each, while a single plan needs about 60–100 locations.
- **Open-Meteo:** hourly gusts, separate rain and snow, and many locations per request. But the free tier is non-commercial and capped per IP (that's what failed on Render), and the price of the commercial "customer" API was only shown at checkout. It's still supported as an optional provider (`open-meteo` in `WEATHER_PROVIDERS`, plus `OPEN_METEO_API_KEY` for the customer endpoint).
