import type { Ref } from 'react'
import type { TripPlan } from '../../api/types'
import { Disclosure } from '../../components/Disclosure'
import { AlertIcon, BlockIcon, CheckCircleIcon, InfoIcon } from '../../components/icons'
import { formatClock, formatDuration, formatMiles, formatRiskMiles } from '../../lib/format'

const TONE = {
  recommended: { box: 'border-green-200 bg-green-50', title: 'text-green-900', icon: 'text-green-700', Icon: CheckCircleIcon },
  provisional: { box: 'border-amber-300 bg-amber-50', title: 'text-amber-900', icon: 'text-amber-700', Icon: AlertIcon },
  no_travel: { box: 'border-purple-200 bg-purple-50', title: 'text-purple-900', icon: 'text-purple-700', Icon: BlockIcon },
  no_forecast: { box: 'border-slate-300 bg-slate-50', title: 'text-slate-900', icon: 'text-slate-600', Icon: AlertIcon },
} as const

interface Props {
  plan: TripPlan
  /** Focused when a new plan arrives, so keyboard and screen-reader users land on the answer. */
  headingRef?: Ref<HTMLHeadingElement>
}

export function RecommendationBanner({ plan, headingRef }: Props) {
  const { recommendation: rec, notices } = plan
  const tone =
    rec.status === 'none' ? TONE[rec.none_reason === 'no_forecast' ? 'no_forecast' : 'no_travel'] : TONE[rec.status]
  const title =
    rec.status === 'recommended'
      ? `Recommended: Route ${rec.route_id}`
      : rec.status === 'provisional'
        ? `Provisional pick: Route ${rec.route_id}`
        : rec.none_reason === 'no_forecast'
          ? 'Weather unavailable: no route can be assessed'
          : 'No safe route at this departure time'
  const picked = plan.routes.find((r) => r.id === rec.route_id)
  const coverage = picked ? Math.floor(picked.summary.forecast_coverage * 1000) / 10 : null

  return (
    <div className="space-y-3">
      <section aria-labelledby="recommendation-title" className={`rounded-lg border p-4 ${tone.box}`}>
        <div className="flex gap-3">
          <tone.Icon className={`mt-0.5 h-5 w-5 shrink-0 ${tone.icon}`} />
          <div className="min-w-0 flex-1">
            <h2
              id="recommendation-title"
              ref={headingRef}
              tabIndex={-1}
              className={`text-base font-semibold focus:outline-none ${tone.title}`}
            >
              {title}
            </h2>
            {picked && (
              <p className="mt-1 text-sm text-slate-700 tabular-nums">
                {formatMiles(picked.distance_mi)} · {formatDuration(picked.duration_s)} drive · arrives{' '}
                {formatClock(picked.arrival_time)}
                <br />
                {formatRiskMiles(picked.summary.miles_by_level.severe)} Severe mi ·{' '}
                {formatRiskMiles(picked.summary.miles_by_level.high)} High mi · {coverage}% forecast
              </p>
            )}
            <p className="mt-2 text-sm text-slate-800">{rec.reason}</p>
            {rec.exclusions.length > 0 && (
              <ul className="mt-2 space-y-1 text-sm text-slate-700">
                {rec.exclusions.map((e) => (
                  <li key={e.route_id} className="flex gap-2">
                    <BlockIcon className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
                    <span>{e.reason}</span>
                  </li>
                ))}
              </ul>
            )}
            <Disclosure summary="How routes are ranked" className="mt-3 text-sm">
              <p className="mt-1 leading-relaxed text-slate-600">
                Routes are ranked exactly as the assessment specifies: fewest Severe miles, then fewest High miles,
                then lowest average risk, then shortest drive time. As a separate safety constraint, a route with any
                No Travel conditions is never recommended, and a route missing forecasts can only be a provisional
                pick when no fully forecast route exists.
              </p>
            </Disclosure>
          </div>
        </div>
      </section>

      {rec.warnings.map((msg) => (
        <p key={msg} className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{msg}</span>
        </p>
      ))}
      {notices.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            <InfoIcon className="h-3.5 w-3.5" />
            Notes
          </p>
          <ul className="space-y-1.5 text-sm text-slate-700">
            {notices.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
