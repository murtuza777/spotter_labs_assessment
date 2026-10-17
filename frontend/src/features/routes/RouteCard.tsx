import { memo } from 'react'
import type { PlannedRoute } from '../../api/types'
import { formatClock, formatDuration, formatMiles, formatRiskMiles } from '../../lib/format'
import { riskColor, riskLabel } from '../../lib/risk'
import { RiskMilesBar } from './RiskMilesBar'

interface Props {
  route: PlannedRoute
  /** Set on the route the backend picked: a firm recommendation or a provisional one. */
  pick: 'recommended' | 'provisional' | null
  selected: boolean
  onSelect: (id: string) => void
  onHover: (id: string | null) => void
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="text-sm font-medium text-slate-800" style={color ? { color } : undefined}>
        {value}
      </dd>
    </div>
  )
}

function Badge({ route, pick }: { route: PlannedRoute; pick: Props['pick'] }) {
  if (pick === 'recommended')
    return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">★ Recommended</span>
  if (pick === 'provisional')
    return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">Provisional pick</span>
  if (route.eligibility === 'no_travel')
    return <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[11px] font-semibold text-purple-900">Not eligible: No Travel</span>
  if (route.eligibility === 'incomplete_forecast')
    return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700">Not eligible: missing forecast</span>
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
      className={`w-full rounded-lg border p-3 text-left transition ${
        selected ? 'border-sky-500 bg-sky-50/60 ring-1 ring-sky-500' : 'border-slate-200 bg-white hover:border-slate-300'
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">
            {route.id}
          </span>
          <span className="text-sm font-semibold text-slate-900">Route {route.id}</span>
          <Badge route={route} pick={pick} />
        </div>
        <span className="text-xs text-slate-500" title="Position in the ranking">
          #{route.rank}
        </span>
      </div>

      <dl className="grid grid-cols-4 gap-x-2 gap-y-1.5">
        <Stat label="Distance" value={formatMiles(route.distance_mi)} />
        <Stat label="Drive" value={formatDuration(route.duration_s)} />
        <Stat label="ETA" value={formatClock(route.arrival_time)} />
        <Stat label="Worst" value={riskLabel(s.max_level)} />
        {/* The ranking criteria, in ranking order (drive time is above), plus coverage. */}
        <Stat label="Severe mi" value={formatRiskMiles(s.miles_by_level.severe)} color={s.miles_by_level.severe > 0 ? riskColor('severe') : undefined} />
        <Stat label="High mi" value={formatRiskMiles(s.miles_by_level.high)} color={s.miles_by_level.high > 0 ? riskColor('high') : undefined} />
        <Stat label="Avg risk" value={s.avg_risk.toFixed(2)} />
        <Stat label="Forecast" value={`${coverage}%`} color={coverage < 100 ? '#475569' : undefined} />
      </dl>

      <div className="mt-2">
        <RiskMilesBar summary={s} total={route.distance_mi} />
      </div>

      {(s.miles_by_level.no_travel > 0 || s.unknown_miles > 0.05 || route.source === 'detour') && (
        <ul className="mt-2 space-y-1 text-[11px]">
          {s.miles_by_level.no_travel > 0 && (
            <li className="rounded bg-purple-100 px-2 py-1 font-semibold text-purple-900">
              ⚠ No Travel conditions on {formatRiskMiles(s.miles_by_level.no_travel)} mi of this route
            </li>
          )}
          {s.unknown_miles > 0.05 && (
            <li className="rounded bg-slate-100 px-2 py-1 text-slate-700">
              No forecast for {formatRiskMiles(s.unknown_miles)} mi: those miles are unscored, not safe
            </li>
          )}
          {route.source === 'detour' && (
            <li className="rounded bg-amber-50 px-2 py-1 text-amber-900">
              Detour option: TomTom truck routing through a waypoint placed by this app (shown on
              the map), not a TomTom alternative
            </li>
          )}
        </ul>
      )}
    </button>
  )
})
