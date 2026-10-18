import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api/client'
import { useHeatmap, usePlanTrip } from './api/queries'
import type { PlanRequest, PlannedRoute, TripPlan } from './api/types'
import { AlertIcon, RouteIcon } from './components/icons'
import { PlanProgress } from './features/planner/PlanProgress'
import { TripForm } from './features/planner/TripForm'
import { TripSummary } from './features/planner/TripSummary'
import { CheckpointList } from './features/routes/CheckpointList'
import { RecommendationBanner } from './features/routes/RecommendationBanner'
import { RouteCard } from './features/routes/RouteCard'
import { ForecastDock } from './features/timeline/ForecastDock'
import { defaultRouteId } from './lib/routeModel'
import { useTripStore } from './store/tripStore'

// MapLibre is ~1 MB; load it in its own chunk so the form is interactive immediately.
const TripMap = lazy(() => import('./features/map/TripMap'))

// Single-column layout (below lg): readable line length for the panel sections.
const NARROW = 'max-lg:mx-auto max-lg:w-full max-lg:max-w-3xl'

function pickOf(plan: TripPlan, route: PlannedRoute): 'recommended' | 'provisional' | null {
  if (route.id !== plan.recommended_route_id) return null
  return plan.recommendation.status === 'provisional' ? 'provisional' : 'recommended'
}

/** How the selected route stands, in words, for the forecast dock. */
function routeStatus(plan: TripPlan, route: PlannedRoute): string {
  const pick = pickOf(plan, route)
  if (pick === 'recommended') return 'recommended'
  if (pick === 'provisional') return 'provisional pick'
  if (route.eligibility === 'no_travel') return 'not eligible: No Travel'
  if (route.eligibility !== 'eligible') return 'not eligible: missing forecast'
  return `alternative, ranked #${route.rank}`
}

function App() {
  const planMutation = usePlanTrip()
  const { mutate } = planMutation
  const plan = planMutation.data
  const pending = planMutation.isPending
  const heatmap = useHeatmap(plan)
  const [editing, setEditing] = useState(true)
  const tripRef = useRef<HTMLElement>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)

  const selectedRouteId = useTripStore((s) => s.selectedRouteId)
  const selectRoute = useTripStore((s) => s.selectRoute)
  const hoverRoute = useTripStore((s) => s.hoverRoute)
  const resetForPlan = useTripStore((s) => s.resetForPlan)

  useEffect(() => {
    if (plan) resetForPlan(defaultRouteId(plan))
  }, [plan, resetForPlan])

  const submit = useCallback(
    (req: PlanRequest) =>
      // onSuccess only fires for the latest request, so an older response can't take over.
      mutate(req, {
        onSuccess: () => {
          setEditing(false)
          // Land on the answer: keyboard and screen-reader users hear the recommendation.
          requestAnimationFrame(() => headingRef.current?.focus())
        },
      }),
    [mutate],
  )

  const editTrip = () => {
    setEditing(true)
    requestAnimationFrame(() => tripRef.current?.querySelector<HTMLInputElement>('input')?.focus())
  }

  const error = planMutation.error
  const apiError = error instanceof ApiError ? error : null
  const showForm = !plan || editing
  const selected = plan?.routes.find((r) => r.id === (selectedRouteId ?? defaultRouteId(plan)))
  const orderedRoutes = plan ? [...plan.routes].sort((a, b) => a.rank - b.rank) : []
  const weatherSources = [
    ...new Set([...(plan?.meta?.weather_sources ?? []), ...(heatmap.data?.meta?.weather_sources ?? [])]),
  ]
  const results = plan && !pending ? plan : undefined

  return (
    <main className="flex min-h-dvh flex-col bg-white lg:grid lg:h-dvh lg:min-h-0 lg:grid-cols-[clamp(22rem,30vw,27rem)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
      {/* The panel: a scrolling column on wide screens. On narrow ones its sections join the
          page flow around the map (display: contents + order), so the map never remounts. */}
      <div className="contents lg:col-start-1 lg:row-start-1 lg:flex lg:min-h-0 lg:flex-col lg:overflow-y-auto lg:border-r lg:border-slate-200">
        <header className="order-1 border-b border-slate-200 bg-white">
          <div className={`flex items-center gap-3 px-4 py-3 ${NARROW}`}>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white" aria-hidden="true">
              <RouteIcon className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <h1 className="text-[15px] leading-tight font-semibold text-slate-900">Weather-Aware Truck Routing</h1>
              <p className="text-[13px] leading-tight text-slate-500">Forecast risk at each checkpoint's arrival time</p>
            </div>
          </div>
        </header>

        <section ref={tripRef} aria-label="Trip" className={`order-2 px-4 pt-4 ${NARROW}`}>
          {!showForm && plan && <TripSummary request={plan.request} onEdit={editTrip} />}
          <div hidden={!showForm}>
            {plan && (
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-slate-900">Edit trip</h2>
                {!pending && (
                  <button
                    type="button"
                    onClick={() => setEditing(false)}
                    className="h-10 rounded-md px-3 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
                  >
                    Cancel
                  </button>
                )}
              </div>
            )}
            <TripForm
              onSubmit={submit}
              isPending={pending}
              serverErrors={apiError?.code === 'invalid_request' ? apiError.details : undefined}
            />
          </div>
        </section>

        <div className={`order-3 space-y-3 px-4 pt-4 pb-4 lg:pb-0 ${NARROW}`}>
          {pending && <PlanProgress />}

          {error && !pending && apiError?.code !== 'invalid_request' && (
            <div className="flex gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
              <AlertIcon className="mt-0.5 h-5 w-5 shrink-0 text-red-700" />
              <div className="min-w-0">
                <p className="font-semibold">Couldn't plan this trip</p>
                <p className="mt-0.5">{error.message}</p>
                <p className="mt-1 text-red-800">Check the trip details, or try again in a moment.</p>
                {planMutation.variables && (
                  <button
                    type="button"
                    onClick={() => submit(planMutation.variables!)}
                    className="mt-3 h-10 rounded-md border border-red-300 bg-white px-4 font-medium text-red-900 transition hover:bg-red-100"
                  >
                    Try again
                  </button>
                )}
              </div>
            </div>
          )}

          {results && <RecommendationBanner plan={results} headingRef={headingRef} />}

          {!plan && !pending && !error && (
            <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600">
              <p className="font-semibold text-slate-900">No trip planned yet</p>
              <p className="mt-1">Pick a demo trip or enter an origin and destination. You'll get:</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>Up to 3 truck routes, routed for your load weight</li>
                <li>The forecast for the hour the truck reaches each checkpoint</li>
                <li>A pick ranked by Severe miles, then High miles, average risk and drive time</li>
              </ul>
            </div>
          )}
        </div>

        {results && (
          <section aria-label="Route options" className="order-5 px-4 pt-5 max-lg:mx-auto max-lg:w-full max-lg:max-w-5xl">
            <h2 className="mb-2 text-sm font-semibold text-slate-900">
              Compare routes <span className="font-normal text-slate-500">· best first</span>
            </h2>
            <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-1">
              {orderedRoutes.map((route) => (
                <RouteCard
                  key={route.id}
                  route={route}
                  pick={pickOf(results, route)}
                  selected={route.id === selected?.id}
                  onSelect={selectRoute}
                  onHover={hoverRoute}
                />
              ))}
            </div>
          </section>
        )}

        {results && selected && (
          <section aria-label="Checkpoints" className={`order-6 px-4 pt-6 pb-8 ${NARROW}`}>
            <CheckpointList key={selected.id} route={selected} windMetric={results.request.wind_metric} />
          </section>
        )}
      </div>

      <section
        aria-label="Route map"
        className="order-4 flex flex-col pt-4 lg:col-start-2 lg:row-start-1 lg:min-h-0 lg:pt-0"
      >
        <div className="relative h-[clamp(18rem,60svh,38rem)] w-full shrink-0 border-y border-slate-200 bg-slate-100 max-lg:[@media(max-height:500px)]:h-[80svh] lg:h-auto lg:min-h-0 lg:flex-1 lg:border-y-0">
          <Suspense
            fallback={<div className="flex h-full items-center justify-center text-sm text-slate-500">Loading map…</div>}
          >
            <TripMap plan={results} heatmap={heatmap.data} pending={pending} />
          </Suspense>
        </div>
        {results && (
          <ForecastDock
            departure={results.request.departure_time}
            route={selected ?? null}
            routeStatus={selected ? routeStatus(results, selected) : undefined}
            heatmapState={heatmap.isError ? 'error' : heatmap.data ? 'ready' : 'loading'}
            onRetry={() => heatmap.refetch()}
            gridStepDeg={heatmap.data?.grid_step_deg}
            weatherSources={weatherSources}
          />
        )}
      </section>
    </main>
  )
}

export default App
