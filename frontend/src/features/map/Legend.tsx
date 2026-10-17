import { METRIC_THRESHOLDS, METRIC_UNIT, RISK_COLOR, RISK_LABEL, RISK_LEVELS } from '../../lib/risk'
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
    <div className="absolute top-3 left-3 z-10 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-[11px] shadow-sm backdrop-blur">
      <p className="mb-1 font-semibold text-slate-700">
        Risk level{thresholds && <span className="font-normal text-slate-500"> · {unit}</span>}
      </p>
      <ul className="space-y-0.5">
        {RISK_LEVELS.map((level, i) => (
          <li key={level} className="flex items-center gap-2">
            <span className="h-2.5 w-4 rounded-sm" style={{ backgroundColor: RISK_COLOR[level] }} />
            <span className="w-16 text-slate-700">{RISK_LABEL[level]}</span>
            {thresholds && <span className="tabular-nums text-slate-500">{rangeFor(i)}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
