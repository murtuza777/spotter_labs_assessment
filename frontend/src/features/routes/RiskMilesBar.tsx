import type { RouteSummary } from '../../api/types'
import { formatRiskMiles } from '../../lib/format'
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS } from '../../lib/risk'

// Missing forecasts are hatched, never a flat color that could pass for a risk level.
const UNKNOWN_FILL = 'repeating-linear-gradient(135deg, #94a3b8 0 2px, #e2e8f0 2px 5px)'

export function RiskMilesBar({ summary, total }: { summary: RouteSummary; total: number }) {
  const parts = [
    ...RISK_LEVELS.map((level) => ({
      key: level,
      miles: summary.miles_by_level[level],
      fill: RISK_COLOR[level],
      label: RISK_LABEL[level],
    })),
    { key: 'unknown', miles: summary.unknown_miles, fill: UNKNOWN_FILL, label: 'No forecast' },
  ].filter((p) => p.miles > 0)
  const description = `Miles by risk level: ${parts.map((p) => `${p.label} ${formatRiskMiles(p.miles)} mi`).join(', ')}`

  return (
    <span className="flex h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-100" role="img" aria-label={description}>
      {parts.map((p) => (
        <span
          key={p.key}
          title={`${p.label}: ${formatRiskMiles(p.miles)} mi`}
          className="block h-full"
          style={{ width: `${(p.miles / total) * 100}%`, background: p.fill }}
        />
      ))}
    </span>
  )
}
