import { memo } from 'react'
import type { PlannedRoute } from '../../api/types'
import { formatClock, formatDuration, formatMiles } from '../../lib/format'
import { riskColor, riskLabel } from '../../lib/risk'
import { RiskMilesBar } from './RiskMilesBar'

interface Props {
  route: PlannedRoute
  recommended: boolean
  selected: boolean
  onSelect: (id: string) => void
  onHover: (id: string | null) => void
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className={`text-sm font-medium ${tone ?? 'text-slate-800'}`}>{value}</dd>
    </div>
  )
}

export const RouteCard = memo(function RouteCard({ route, recommended, selected, onSelect, onHover }: Props) {
  const s = route.summary
  const level = s.max_level
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
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">
            {route.id}
          </span>
          <span className="text-sm font-semibold text-slate-900">Route {route.id}</span>
          {recommended && (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
              ★ Recommended
            </span>
          )}
        </div>
        <span className="text-xs text-slate-500">#{route.rank}</span>
      </div>

      <dl className="mb-2 grid grid-cols-4 gap-2">
        <Stat label="Distance" value={formatMiles(route.distance_mi)} />
        <Stat label="Drive" value={formatDuration(route.duration_s)} />
        <Stat label="Arrive" value={formatClock(route.arrival_time)} />
        <Stat label="Worst" value={riskLabel(level)} tone="font-semibold" />
      </dl>

      <RiskMilesBar summary={s} total={route.distance_mi} />
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
        <span>
          <b className="font-semibold" style={{ color: riskColor('no_travel') }}>
            {Math.round(s.miles_by_level.no_travel)}
          </b>{' '}
          no-travel mi
        </span>
        <span>
          <b className="font-semibold" style={{ color: riskColor('severe') }}>
            {Math.round(s.miles_by_level.severe)}
          </b>{' '}
          severe mi
        </span>
        <span>
          <b className="font-semibold" style={{ color: riskColor('high') }}>
            {Math.round(s.miles_by_level.high)}
          </b>{' '}
          high mi
        </span>
        <span>avg risk {s.avg_risk.toFixed(2)}</span>
        {route.source === 'detour' && <span className="italic">via detour</span>}
      </div>
    </button>
  )
})
