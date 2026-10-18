import { memo } from 'react'
import type { PlannedRoute } from '../../api/types'
import { RiskBadge } from '../../components/RiskBadge'
import { AlertIcon, BlockIcon, CheckCircleIcon, InfoIcon } from '../../components/icons'
import { formatClock, formatDuration, formatMiles, formatRiskMiles } from '../../lib/format'
import { RiskMilesBar } from './RiskMilesBar'

interface Props {
  route: PlannedRoute
  /** Set on the route the backend picked: a firm recommendation or a provisional one. */
  pick: 'recommended' | 'provisional' | null
  selected: boolean
  onSelect: (id: string) => void
  onHover: (id: string | null) => void
}

// Everything inside the card is phrasing content (spans), as a <button> requires.
function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <span className="block min-w-0">
      <span className="block text-xs text-slate-500">{label}</span>
      <span className={`block text-[15px] font-semibold tabular-nums ${tone ?? 'text-slate-900'}`}>{value}</span>
    </span>
  )
}

const STATUS_TEXT = {
  recommended: 'recommended',
  provisional: 'provisional pick',
} as const

/** A short spoken summary; the visible card holds the full detail. */
function cardLabel(route: PlannedRoute, pick: Props['pick'], coverage: number): string {
  const s = route.summary
  const status = pick
    ? STATUS_TEXT[pick]
    : route.eligibility === 'no_travel'
      ? 'not eligible, No Travel conditions'
      : route.eligibility === 'eligible'
        ? ''
        : 'not eligible, missing forecast'
  return [
    `Route ${route.id}${status ? `, ${status}` : ''}, ranked ${route.rank}`,
    `${formatMiles(route.distance_mi)}, ${formatDuration(route.duration_s)} drive, arrives ${formatClock(route.arrival_time)}`,
    `${formatRiskMiles(s.miles_by_level.severe)} Severe miles, ${formatRiskMiles(s.miles_by_level.high)} High miles, average risk ${s.avg_risk.toFixed(2)}, ${coverage}% forecast`,
    s.miles_by_level.no_travel > 0 ? `No Travel on ${formatRiskMiles(s.miles_by_level.no_travel)} miles` : '',
    s.unknown_miles > 0.05 ? `no forecast for ${formatRiskMiles(s.unknown_miles)} miles` : '',
    route.source === 'detour' ? 'detour through a waypoint' : '',
  ]
    .filter(Boolean)
    .join('. ')
}

function StatusBadge({ route, pick }: { route: PlannedRoute; pick: Props['pick'] }) {
  const base = 'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold whitespace-nowrap'
  if (pick === 'recommended')
    return (
      <span className={`${base} bg-green-100 text-green-800`}>
        <CheckCircleIcon className="h-3.5 w-3.5" />
        Recommended
      </span>
    )
  if (pick === 'provisional')
    return (
      <span className={`${base} bg-amber-100 text-amber-900`}>
        <AlertIcon className="h-3.5 w-3.5" />
        Provisional pick
      </span>
    )
  if (route.eligibility === 'no_travel')
    return (
      <span className={`${base} bg-purple-100 text-purple-900`}>
        <BlockIcon className="h-3.5 w-3.5" />
        Not eligible: No Travel
      </span>
    )
  if (route.eligibility === 'incomplete_forecast' || route.eligibility === 'insufficient_forecast')
    return (
      <span className={`${base} bg-slate-100 text-slate-700`}>
        <AlertIcon className="h-3.5 w-3.5" />
        Not eligible: missing forecast
      </span>
    )
  return null
}

export const RouteCard = memo(function RouteCard({ route, pick, selected, onSelect, onHover }: Props) {
  const s = route.summary
  const coverage = Math.floor(s.forecast_coverage * 1000) / 10
  return (
    <button
      type="button"
      onClick={() => onSelect(route.id)}
      onMouseEnter={() => onHover(route.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(route.id)}
      onBlur={() => onHover(null)}
      aria-pressed={selected}
      aria-label={cardLabel(route, pick, coverage)}
      className={`@container relative block w-full rounded-lg border bg-white p-3.5 text-left transition ${
        selected
          ? 'border-brand-600 shadow-sm ring-1 ring-brand-600'
          : 'border-slate-200 hover:border-slate-300 hover:shadow-sm active:bg-slate-50'
      }`}
    >
      <span className="flex items-start justify-between gap-2">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-sm font-bold ${
              selected ? 'bg-brand-600 text-white' : 'bg-slate-800 text-white'
            }`}
            aria-hidden="true"
          >
            {route.id}
          </span>
          <span className="text-[15px] font-semibold text-slate-900">Route {route.id}</span>
          <StatusBadge route={route} pick={pick} />
        </span>
        <span className="shrink-0 text-xs font-medium text-slate-500 tabular-nums">
          <span className="sr-only">Ranked </span>#{route.rank}
        </span>
      </span>

      <span className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 @[19rem]:grid-cols-3">
        <Stat label="Distance" value={formatMiles(route.distance_mi)} />
        <Stat label="Drive" value={formatDuration(route.duration_s)} />
        <Stat label="ETA" value={formatClock(route.arrival_time)} />
      </span>
      {/* The ranking criteria, in ranking order (drive time is above), plus coverage. */}
      <span className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-slate-100 pt-2 @[19rem]:grid-cols-4">
        <Stat
          label="Severe mi"
          value={formatRiskMiles(s.miles_by_level.severe)}
          tone={s.miles_by_level.severe > 0 ? 'text-red-700' : undefined}
        />
        <Stat
          label="High mi"
          value={formatRiskMiles(s.miles_by_level.high)}
          tone={s.miles_by_level.high > 0 ? 'text-orange-700' : undefined}
        />
        <Stat label="Avg risk" value={s.avg_risk.toFixed(2)} />
        <Stat label="Forecast" value={`${coverage}%`} tone={coverage < 100 ? 'text-slate-600' : undefined} />
      </span>

      <span className="mt-3 flex items-center gap-2">
        <RiskMilesBar summary={s} total={route.distance_mi} />
        <span className="shrink-0 text-xs text-slate-500">Worst</span>
        <RiskBadge level={s.max_level} />
      </span>

      {(s.miles_by_level.no_travel > 0 || s.unknown_miles > 0.05 || route.source === 'detour') && (
        <span className="mt-3 block space-y-1.5 text-[13px]">
          {s.miles_by_level.no_travel > 0 && (
            <span className="flex gap-1.5 rounded-md bg-purple-50 px-2 py-1.5 font-medium text-purple-900">
              <BlockIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>No Travel conditions on {formatRiskMiles(s.miles_by_level.no_travel)} mi of this route</span>
            </span>
          )}
          {s.unknown_miles > 0.05 && (
            <span className="flex gap-1.5 rounded-md border border-dashed border-slate-300 px-2 py-1.5 text-slate-700">
              <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>No forecast for {formatRiskMiles(s.unknown_miles)} mi: those miles are unscored, not safe</span>
            </span>
          )}
          {route.source === 'detour' && (
            <span className="flex gap-1.5 rounded-md bg-amber-50 px-2 py-1.5 text-amber-900">
              <InfoIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Detour option: TomTom truck routing through a waypoint placed by this app (shown on the map), not a
                TomTom alternative
              </span>
            </span>
          )}
        </span>
      )}
      {selected && (
        <span className="mt-3 block text-xs font-medium text-brand-700" aria-hidden="true">
          Shown on the map
        </span>
      )}
    </button>
  )
})
