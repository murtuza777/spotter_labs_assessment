import type { TripPlan } from '../../api/types'

const TONE = {
  recommended: { box: 'border-emerald-200 bg-emerald-50', title: 'text-emerald-900', body: 'text-emerald-800' },
  provisional: { box: 'border-amber-300 bg-amber-50', title: 'text-amber-900', body: 'text-amber-800' },
  none: { box: 'border-purple-300 bg-purple-50', title: 'text-purple-900', body: 'text-purple-800' },
} as const

export function RecommendationBanner({ plan }: { plan: TripPlan }) {
  const { recommendation: rec, notices } = plan
  const tone = TONE[rec.status]
  const title =
    rec.status === 'recommended'
      ? `Recommended: Route ${rec.route_id}`
      : rec.status === 'provisional'
        ? `Provisional pick: Route ${rec.route_id}`
        : rec.none_reason === 'no_forecast'
          ? '⚠ Weather unavailable: no route can be assessed'
          : '⚠ No safe route at this departure time'

  return (
    <div className="space-y-2">
      <div className={`rounded-lg border p-3 ${tone.box}`} role="status">
        <p className={`text-sm font-semibold ${tone.title}`}>{title}</p>
        <p className={`mt-0.5 text-sm ${tone.body}`}>{rec.reason}</p>
        {rec.exclusions.length > 0 && (
          <ul className={`mt-1.5 list-disc space-y-0.5 pl-4 text-xs ${tone.body}`}>
            {rec.exclusions.map((e) => (
              <li key={e.route_id}>{e.reason}</li>
            ))}
          </ul>
        )}
        <details className="mt-1.5 text-[11px] text-slate-600">
          <summary className="cursor-pointer select-none">How routes are ranked</summary>
          <p className="mt-1 leading-relaxed">
            Routes are ranked exactly as the assessment specifies: fewest Severe miles, then fewest
            High miles, then lowest average risk, then shortest drive time. As a separate safety
            constraint, a route with any No Travel conditions is never recommended, and a route
            missing forecasts can only be a provisional pick when no fully forecast route exists.
          </p>
        </details>
      </div>
      {[...rec.warnings, ...notices].map((msg) => (
        <p key={msg} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {msg}
        </p>
      ))}
    </div>
  )
}
