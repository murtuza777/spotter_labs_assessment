import { memo, useState } from 'react'
import type { Checkpoint, PlannedRoute, WindMetric } from '../../api/types'
import { RiskBadge } from '../../components/RiskBadge'
import { formatClock } from '../../lib/format'
import { useTripStore } from '../../store/tripStore'

// Long routes have dozens of checkpoints; show the first stretch and let the user expand.
const INITIAL_ROWS = 10

interface Props {
  route: PlannedRoute
  windMetric: WindMetric
}

function weatherSummary(cp: Checkpoint, windMetric: WindMetric): string | null {
  const w = cp.weather
  if (!w) return null
  const parts = [`${Math.round(windMetric === 'gust' ? w.gust_mph : w.wind_mph)} mph ${windMetric === 'gust' ? 'gust' : 'wind'}`]
  if (w.rain_in_hr >= 0.01) parts.push(`${w.rain_in_hr.toFixed(2)} in/hr rain`)
  if (w.snow_in_hr >= 0.01) parts.push(`${w.snow_in_hr.toFixed(2)} in/hr snow`)
  return parts.join(' · ')
}

export const CheckpointList = memo(function CheckpointList({ route, windMetric }: Props) {
  const focusCheckpoint = useTripStore((s) => s.focusCheckpoint)
  const focusedIndex = useTripStore((s) => (s.focused?.routeId === route.id ? s.focused.index : null))
  const [expanded, setExpanded] = useState(false)
  const total = route.checkpoints.length
  // A checkpoint picked on the map stays visible even when the list is collapsed.
  const showAll = expanded || (focusedIndex !== null && focusedIndex >= INITIAL_ROWS)
  const rows = showAll ? route.checkpoints : route.checkpoints.slice(0, INITIAL_ROWS)

  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-900">
        Route {route.id} checkpoints ({total})
      </h3>
      <p className="mt-0.5 mb-2 text-sm text-slate-500">
        The forecast for the hour the truck reaches each one. Select one for its full risk breakdown.
      </p>
      <ol className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 bg-white">
        {rows.map((cp) => {
          const summary = weatherSummary(cp, windMetric)
          const focused = focusedIndex === cp.index
          return (
            <li key={cp.index}>
              <button
                type="button"
                onClick={() => focusCheckpoint({ routeId: route.id, index: cp.index })}
                aria-current={focused ? 'true' : undefined}
                data-checkpoint-row={`${route.id}-${cp.index}`}
                className={`grid min-h-12 w-full grid-cols-[3.75rem_minmax(0,1fr)_auto] items-center gap-x-3 px-3 py-2 text-left text-sm transition hover:bg-slate-50 active:bg-slate-100 ${
                  focused ? 'bg-brand-50 shadow-[inset_3px_0_0_var(--color-brand-600)]' : ''
                }`}
              >
                <span className="font-medium text-slate-900 tabular-nums">mi {Math.round(cp.mile)}</span>
                <span className="min-w-0">
                  <span className="block text-slate-700 tabular-nums">{formatClock(cp.eta)}</span>
                  {summary ? (
                    <span className="block text-xs text-slate-500">{summary}</span>
                  ) : (
                    <span className="block text-xs text-slate-500">Unscored, not assumed safe</span>
                  )}
                </span>
                <RiskBadge level={cp.risk?.level} />
              </button>
            </li>
          )
        })}
      </ol>
      {total > INITIAL_ROWS && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={showAll}
          className="mt-2 h-10 w-full rounded-md border border-slate-300 bg-white text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          {showAll ? 'Show fewer checkpoints' : `Show all ${total} checkpoints`}
        </button>
      )}
    </div>
  )
})
