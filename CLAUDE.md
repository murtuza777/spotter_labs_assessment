# Project: Weather-Aware Truck Routing (Spotter AI assessment)

The source of truth for scope, interpretations and the phase checklist is `docs/project-log/IMPLEMENTATION_PLAN.md`. Read it before starting work. Tick off checklist items and log hours in `docs/project-log/PROGRESS.md` (hard cap: 16 h).

## Layout
- `backend/`: Django 5.2 + DRF, managed with **uv** (`uv run …`; never use pip). App: `planner/`.
  - `planner/domain/`: pure Python only (no Django, no I/O). All risk, sampling, scoring and recommendation logic lives here and is unit-tested.
  - `planner/providers/`: third-party HTTP clients (TomTom, Open-Meteo, Photon) behind Protocols in `base.py`.
  - `planner/services/`: orchestration, batching and caching. `views.py` and `serializers.py` stay thin.
- `frontend/`: Vite + React 19 + strict TS + Tailwind 4 + MapLibre (`react-map-gl/maplibre`) + TanStack Query + Zustand.

## Commands
- Backend: `uv run pytest`, `uv run ruff check .`, `uv run python manage.py runserver` (from `backend/`)
- Frontend: `npm run dev | lint | typecheck | test | build` (from `frontend/`). The dev server proxies `/api` to `127.0.0.1:8000`.

## Rules
- The risk thresholds and tie-break order are specified in plan §2. Don't change them silently. If one changes, update the plan, the tests and the README.
- Map performance matters (40% of the grade). Use WebGL layers, not DOM markers. The forecast slider changes paint properties only, never re-uploads data.
- Secrets live only in `backend/.env` (gitignored). Never commit keys.
