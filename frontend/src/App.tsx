import { Suspense, lazy, useCallback, useEffect } from 'react'
import { ApiError } from './api/client'
import { useHeatmap, usePlanTrip } from './api/queries'
import type { PlanRequest } from './api/types'
import { PlanProgress } from './features/planner/PlanProgress'
import { TripForm } from './features/planner/TripForm'
import { CheckpointList } from './features/routes/CheckpointList'
import { RecommendationBanner } from './features/routes/RecommendationBanner'
import { RouteCard } from './features/routes/RouteCard'
import { ForecastSlider } from './features/timeline/ForecastSlider'
import { useTripStore } from './store/tripStore'

// MapLibre is ~1 MB; load it in its own chunk so the form is interactive immediately.
const TripMap = lazy(() => import('./features/map/TripMap'))

function App() {
  const planMutation = usePlanTrip()
  const plan = planMutation.data
  const heatmap = useHeatmap(plan)

  const selectedRouteId = useTripStore((s) => s.selectedRouteId)
  const selectRoute = useTripStore((s) => s.selectRoute)
  const hoverRoute = useTripStore((s) => s.hoverRoute)
  const resetForPlan = useTripStore((s) => s.resetForPlan)

  useEffect(() => {
    if (plan) resetForPlan(plan.recommended_route_id)
  }, [plan, resetForPlan])

  const onSubmit = useCallback((req: PlanRequest) => planMutation.mutate(req), [planMutation])

  const error = planMutation.error
  const apiError = error instanceof ApiError ? error : null
  const selected = plan?.routes.find((r) => r.id === (selectedRouteId ?? plan.recommended_route_id))
  const orderedRoutes = plan ? [...plan.routes].sort((a, b) => a.rank - b.rank) : []

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="order-2 flex min-h-0 w-full shrink-0 flex-col border-t border-slate-200 bg-white md:order-1 md:w-[26rem] md:border-t-0 md:border-r">
        <header className="border-b border-slate-100 px-4 pt-4 pb-3">
          <h1 className="text-base font-bold text-slate-900">Weather-Aware Truck Routing</h1>
          <p className="text-xs text-slate-500">
            3 truck routes, the forecast at each checkpoint's arrival time, and the safest pick.
          </p>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          <TripForm
            onSubmit={onSubmit}
            isPending={planMutation.isPending}
            serverErrors={apiError?.code === 'invalid_request' ? apiError.details : undefined}
          />

          {planMutation.isPending && <PlanProgress />}

          {error && !planMutation.isPending && apiError?.code !== 'invalid_request' && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
              <p className="font-semibold">Couldn't plan this trip</p>
              <p>{error.message}</p>
            </div>
          )}

          {plan && !planMutation.isPending && (
            <section className="space-y-3" aria-label="Route options">
              <RecommendationBanner plan={plan} />
              <div className="space-y-2">
                {orderedRoutes.map((route) => (
                  <RouteCard
                    key={route.id}
                    route={route}
                    recommended={route.id === plan.recommended_route_id}
                    selected={route.id === selected?.id}
                    onSelect={selectRoute}
                    onHover={hoverRoute}
                  />
                ))}
              </div>
              {selected && <CheckpointList route={selected} />}
            </section>
          )}

          {!plan && !planMutation.isPending && !error && (
            <p className="rounded-lg border border-dashed border-slate-200 p-3 text-xs leading-relaxed text-slate-500">
              Pick a demo trip or enter your own. Each route is checked at your chosen spacing, using
              the forecast for the hour the truck reaches that spot, then scored with the risk and
              load rules.
            </p>
          )}
        </div>
      </aside>

      <main className="relative order-1 h-[55vh] min-h-[320px] flex-1 md:order-2 md:h-auto">
        <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-slate-400">Loading map…</div>}>
          <TripMap plan={planMutation.isPending ? undefined : plan} heatmap={heatmap.data} />
        </Suspense>
        {plan && !planMutation.isPending && (
          <div className="pointer-events-none absolute inset-x-2 bottom-2 z-10 mx-auto max-w-3xl sm:inset-x-3 sm:bottom-8">
            <ForecastSlider
              departure={plan.request.departure_time}
              arrivalHours={selected ? selected.duration_s / 3600 : null}
              heatmapState={heatmap.isError ? 'error' : heatmap.data ? 'ready' : 'loading'}
              onRetry={() => heatmap.refetch()}
            />
          </div>
        )}
      </main>
    </div>
  )
}

export default App
