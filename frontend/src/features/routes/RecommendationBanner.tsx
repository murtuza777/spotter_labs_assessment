import type { TripPlan } from '../../api/types'

export function RecommendationBanner({ plan }: { plan: TripPlan }) {
  const { recommendation, notices } = plan
  const best = plan.routes.find((r) => r.id === plan.recommended_route_id)
  // No Travel miles rank first, so the recommended route having any means every route does.
  const noSafeRoute = (best?.summary.miles_by_level.no_travel ?? 0) > 0
  return (
    <div className="space-y-2">
      <div
        className={`rounded-lg border p-3 ${
          noSafeRoute ? 'border-purple-300 bg-purple-50' : 'border-emerald-200 bg-emerald-50'
        }`}
        role="status"
      >
        <p className={`text-sm font-semibold ${noSafeRoute ? 'text-purple-900' : 'text-emerald-900'}`}>
          {noSafeRoute
            ? '⚠ No safe route at this departure time'
            : `Recommended: Route ${plan.recommended_route_id}`}
        </p>
        <p className={`mt-0.5 text-sm ${noSafeRoute ? 'text-purple-800' : 'text-emerald-800'}`}>
          {noSafeRoute && `Least risky option is Route ${plan.recommended_route_id}. `}
          {recommendation.reason}
        </p>
        <p className="mt-1 text-[11px] text-slate-500">
          Ranked by No Travel miles, then forecast coverage, then the brief's order: Severe miles,
          High miles, average risk, drive time.
        </p>
      </div>
      {[...recommendation.warnings, ...notices].map((msg) => (
        <p key={msg} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {msg}
        </p>
      ))}
    </div>
  )
}
