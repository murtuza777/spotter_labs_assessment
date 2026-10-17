import type { HeatmapMetric, RiskLevel } from '../api/types'

export const RISK_LEVELS: RiskLevel[] = ['low', 'moderate', 'high', 'severe', 'no_travel']

export const RISK_LABEL: Record<RiskLevel, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  severe: 'Severe',
  no_travel: 'No Travel',
}

// Color-blind-friendly enough when paired with text labels; never used alone.
export const RISK_COLOR: Record<RiskLevel, string> = {
  low: '#16a34a',
  moderate: '#eab308',
  high: '#f97316',
  severe: '#dc2626',
  no_travel: '#7e22ce',
}

export const UNKNOWN_COLOR = '#94a3b8'

export function riskColor(level: RiskLevel | null | undefined): string {
  return level ? RISK_COLOR[level] : UNKNOWN_COLOR
}

export function riskLabel(level: RiskLevel | null | undefined): string {
  return level ? RISK_LABEL[level] : 'Unknown'
}

/** Thresholds where each metric enters Moderate, High, Severe and No Travel (plan section 2.1). */
export const METRIC_THRESHOLDS: Record<Exclude<HeatmapMetric, 'risk'>, [number, number, number, number]> = {
  gust: [25, 35, 45, 55],
  rain: [0.1, 0.25, 0.5, 1.0],
  snow: [0.5, 1.0, 2.0, 3.0],
}

export const METRIC_LABEL: Record<HeatmapMetric, string> = {
  risk: 'Risk',
  gust: 'Wind',
  rain: 'Rain',
  snow: 'Snow',
}

export const METRIC_UNIT: Record<HeatmapMetric, string> = {
  risk: '',
  gust: 'mph',
  rain: 'in/hr',
  snow: 'in/hr',
}

/**
 * Map a raw value onto the 0-4 risk scale, linearly within each band, so every heatmap
 * metric shares one color ramp and one legend. E.g. 30 mph gusts -> 1.5 (mid Moderate).
 */
export function severityIndex(metric: HeatmapMetric, value: number): number {
  if (metric === 'risk') return value
  const [t1, t2, t3, t4] = METRIC_THRESHOLDS[metric]
  const stops = [0, t1, t2, t3, t4]
  if (value >= t4) return 4
  for (let i = 0; i < 4; i++) {
    if (value < stops[i + 1]) return i + (value - stops[i]) / (stops[i + 1] - stops[i])
  }
  return 4
}
