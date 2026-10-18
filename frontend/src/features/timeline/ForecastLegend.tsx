import { METRIC_LABEL, METRIC_THRESHOLDS, METRIC_UNIT, RISK_COLOR, RISK_LABEL, RISK_LEVELS } from '../../lib/risk'
import { useTripStore } from '../../store/tripStore'

/** The map's color key for the selected heatmap variable, with each band's range. */
export function ForecastLegend() {
  const metric = useTripStore((s) => s.heatmapMetric)
  const thresholds = metric === 'risk' ? null : METRIC_THRESHOLDS[metric]

  const rangeFor = (i: number): string => {
    if (!thresholds) return ''
    if (i === 0) return `< ${thresholds[0]}`
    if (i === 4) return `≥ ${thresholds[3]}`
    return `${thresholds[i - 1]}–${thresholds[i]}`
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-700">
      <span id="map-key" className="font-medium text-slate-500">
        {metric === 'risk' ? 'Risk level' : `${METRIC_LABEL[metric]} (${METRIC_UNIT[metric]})`}
      </span>
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-labelledby="map-key">
        {RISK_LEVELS.map((level, i) => (
          <li key={level} className="flex items-center gap-1.5">
            <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: RISK_COLOR[level] }} aria-hidden="true" />
            <span>{RISK_LABEL[level]}</span>
            {thresholds && <span className="text-slate-500 tabular-nums">{rangeFor(i)}</span>}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="h-3 w-3 shrink-0 rounded-full border-2 border-slate-400 bg-white" aria-hidden="true" />
          <span>No forecast</span>
        </li>
      </ul>
    </div>
  )
}
