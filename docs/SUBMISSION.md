# Submission checklist

Deliverables for the Spotter AI Full Stack Developer assessment: the GitHub repo, the hosted app, and a 5–10 minute Loom. All three go in one reply on the hiring thread.

| Deliverable | Link | Status |
|---|---|---|
| GitHub repository | https://github.com/murtuza777/spotter_labs_assessment | Pushed (`main`) |
| Hosted app | https://murtuza-truck-routing.onrender.com | Deployed on Render; API at https://murtuza-truck-routing-api.onrender.com/api/health/ |
| Loom walkthrough | _add after recording_ | To do. Script: [LOOM_SCRIPT.md](LOOM_SCRIPT.md) |

## Before sending

- [ ] Record the Loom ([script](LOOM_SCRIPT.md)) and paste its URL into this file and the top of the [README](../README.md).
- [ ] Warm the API, then open the live app and plan each demo trip once.
- [ ] Optional: set `WEATHERAPI_KEY` on the Render API service to use the primary provider ([steps](WEATHER_PROVIDERS.md#render-setup)). Without it, forecasts come from NWS alone.
- [ ] Optional during review: set the `API_HEALTH_URL` repository variable so the keep-warm workflow pings the API every 10 minutes. Turn it off afterwards.

## Reply draft

> Hi Ena,
>
> Here is my submission for the Weather-Aware Truck Routing assessment:
>
> - GitHub: https://github.com/murtuza777/spotter_labs_assessment
> - Live app: https://murtuza-truck-routing.onrender.com
> - Loom walkthrough: <Loom URL>
>
> The README opens with a short guide for evaluating the app, and a table mapping each requirement to the code and tests. The API runs on Render's free tier, so the first request after it has been idle can take 30–60 seconds while it wakes.
>
> Thank you,
> MD Murtuza
