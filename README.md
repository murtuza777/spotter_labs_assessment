# Weather-Aware Truck Routing

A React + Django app that helps a truck driver choose the safest route, weighing weather along the way, load weight and travel time.

> Status: work in progress. The full plan is in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md), and the time log is in [docs/PROGRESS.md](docs/PROGRESS.md).

## Stack

- **Frontend:** Vite, React 19, TypeScript, MapLibre GL (via react-map-gl), Tailwind, TanStack Query, Zustand
- **Backend:** Python 3.12, Django 5.2 LTS, Django REST Framework, httpx
- **Providers:** TomTom (truck routing), Open-Meteo (hourly forecast), Photon (geocoding), OpenFreeMap (basemap)

## Run locally

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 20+ and a free [TomTom](https://developer.tomtom.com) API key.

```bash
# backend → http://127.0.0.1:8000
cd backend
cp .env.example .env        # then set TOMTOM_API_KEY
uv sync
uv run python manage.py runserver

# frontend → http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

## Checks

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```
