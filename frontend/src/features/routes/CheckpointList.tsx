import { memo } from 'react'
import type { PlannedRoute } from '../../api/types'
import { formatClock } from '../../lib/format'
import { riskColor, riskLabel } from '../../lib/risk'
import { useTripStore } from '../../store/tripStore'

export const CheckpointList = memo(function CheckpointList({ route }: { route: PlannedRoute }) {
  const focusCheckpoint = useTripStore((s) => s.focusCheckpoint)
  const focusedIndex = useTripStore((s) => (s.focused?.routeId === route.id ? s.focused.index : null))

  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Route {route.id} checkpoints ({route.checkpoints.length})
      </h3>
      <ol className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {route.checkpoints.map((cp) => {
          const level = cp.risk?.level
          const w = cp.weather
          return (
            <li key={cp.index}>
              <button
                type="button"
                onClick={() => focusCheckpoint({ routeId: route.id, index: cp.index })}
                className={`grid w-full grid-cols-[3.5rem_5.5rem_1fr] items-center gap-2 px-2.5 py-1.5 text-left text-xs transition hover:bg-slate-50 ${
                  focusedIndex === cp.index ? 'bg-sky-50' : ''
                }`}
              >
                <span className="tabular-nums text-slate-500">mi {Math.round(cp.mile)}</span>
                <span className="tabular-nums text-slate-700">{formatClock(cp.eta)}</span>
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: riskColor(level) }} />
                  <span className="font-medium text-slate-800">{riskLabel(level)}</span>
                  {w && (
                    <span className="truncate text-slate-400">
                      · {Math.round(w.gust_mph)} mph gust
                      {w.rain_in_hr >= 0.01 && ` · ${w.rain_in_hr.toFixed(2)}" rain`}
                      {w.snow_in_hr >= 0.01 && ` · ${w.snow_in_hr.toFixed(2)}" snow`}
                    </span>
                  )}
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
})
