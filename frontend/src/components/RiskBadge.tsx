import type { RiskLevel } from '../api/types'
import { RISK_COLOR, RISK_TONE, riskLabel } from '../lib/risk'

interface Props {
  level: RiskLevel | null | undefined
  /** Text for a missing level; defaults to "No forecast". */
  unknownLabel?: string
  size?: 'sm' | 'md'
  className?: string
}

/** A risk level as text plus a color dot: never color alone, and Unknown never looks Low. */
export function RiskBadge({ level, unknownLabel = 'No forecast', size = 'sm', className = '' }: Props) {
  const text = level ? riskLabel(level) : unknownLabel
  const pad = size === 'md' ? 'px-2.5 py-1 text-sm' : 'px-2 py-0.5 text-xs'
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border font-semibold whitespace-nowrap ${pad} ${
        RISK_TONE[level ?? 'unknown']
      } ${className}`}
    >
      <RiskDot level={level} />
      {text}
    </span>
  )
}

/** The map's checkpoint symbol: a filled dot per level, a hollow ring for no forecast. */
export function RiskDot({ level }: { level: RiskLevel | null | undefined }) {
  return level ? (
    <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: RISK_COLOR[level] }} />
  ) : (
    <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full border-2 border-slate-400 bg-white" />
  )
}
