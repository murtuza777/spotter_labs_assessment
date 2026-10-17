import type { RouteSummary } from '../../api/types'
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS, UNKNOWN_COLOR } from '../../lib/risk'

export function RiskMilesBar({ summary, total }: { summary: RouteSummary; total: number }) {
  const parts = [
    ...RISK_LEVELS.map((level) => ({
      key: level,
      miles: summary.miles_by_level[level],
      color: RISK_COLOR[level],
      label: RISK_LABEL[level],
    })),
    { key: 'unknown', miles: summary.unknown_miles, color: UNKNOWN_COLOR, label: 'Unknown' },
  ].filter((p) => p.miles > 0)
  const description = parts.map((p) => `${p.label} ${Math.round(p.miles)} mi`).join(', ')

  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-slate-100" role="img" aria-label={description}>
      {parts.map((p) => (
        <div
          key={p.key}
          title={`${p.label}: ${Math.round(p.miles)} mi`}
          style={{ width: `${(p.miles / total) * 100}%`, backgroundColor: p.color }}
        />
      ))}
    </div>
  )
}
