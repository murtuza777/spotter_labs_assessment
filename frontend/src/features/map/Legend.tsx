import { METRIC_THRESHOLDS, METRIC_UNIT, RISK_COLOR, RISK_LABEL, RISK_LEVELS, UNKNOWN_COLOR } from '../../lib/risk'
import { useTripStore } from '../../store/tripStore'

export function Legend() {
  const metric = useTripStore((s) => s.heatmapMetric)
  const thresholds = metric === 'risk' ? null : METRIC_THRESHOLDS[metric]
  const unit = METRIC_UNIT[metric]

  const rangeFor = (i: number): string => {
    if (!thresholds) return ''
    if (i === 0) return `< ${thresholds[0]}`
    if (i === 4) return `≥ ${thresholds[3]}`
    return `${thresholds[i - 1]}–${thresholds[i]}`
  }

  return (
    <div className="absolute top-2 left-2 z-10 rounded-lg border border-slate-200 bg-white/95 px-2 py-1.5 text-[10px] shadow-sm backdrop-blur sm:top-3 sm:left-3 sm:px-3 sm:py-2 sm:text-[11px]">
      <p className="mb-0.5 font-semibold text-slate-700 sm:mb-1">
        Risk level{thresholds && <span className="font-normal text-slate-500"> · {unit}</span>}
      </p>
      <ul className="flex flex-wrap gap-x-2 gap-y-0.5 sm:block sm:space-y-0.5">
        {RISK_LEVELS.map((level, i) => (
          <li key={level} className="flex items-center gap-2">
            <span className="h-2.5 w-4 rounded-sm" style={{ backgroundColor: RISK_COLOR[level] }} />
            <span className="text-slate-700 sm:w-16">{RISK_LABEL[level]}</span>
            {thresholds && <span className="hidden tabular-nums text-slate-500 sm:inline">{rangeFor(i)}</span>}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span className="h-2.5 w-4 rounded-sm" style={{ backgroundColor: UNKNOWN_COLOR }} />
          <span className="text-slate-700">No forecast</span>
        </li>
      </ul>
      <p className="mt-1 hidden max-w-44 text-[10px] leading-snug text-slate-500 sm:block">
        Route and checkpoints: forecast at the truck's ETA. Heatmap: forecast at the slider time;
        grey dots mark grid cells with no forecast for that hour.
      </p>
    </div>
  )
}
