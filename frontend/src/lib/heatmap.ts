import type { ExpressionSpecification } from 'maplibre-gl'
import type { FeatureCollection, Point } from 'geojson'
import type { HeatmapMetric, HeatmapResponse } from '../api/types'
import { RISK_COLOR, severityIndex } from './risk'

export const METRICS: HeatmapMetric[] = ['risk', 'gust', 'rain', 'snow']
const PREFIX: Record<HeatmapMetric, string> = { risk: 'r', gust: 'g', rain: 'p', snow: 's' }

export function propertyName(metric: HeatmapMetric, hour: number): string {
  return `${PREFIX[metric]}${hour}`
}

/**
 * One GeoJSON point per grid cell, carrying every metric for every hour as flat properties
 * (r0..r48, g0..g48, ...). Built once per heatmap response; the slider then only swaps the
 * paint expression, so no data is ever re-uploaded to the GPU.
 *
 * Values are stored as a 0-1 weight: (severityIndex + 1) / 5, so Low still shows a faint
 * tint and each risk band lands on a fixed color stop. Unknown cells get no property.
 */
export function buildHeatmapGeoJSON(data: HeatmapResponse): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: data.points.map(([lat, lon], p) => {
      const properties: Record<string, number> = {}
      for (const metric of METRICS) {
        const frames = data.frames[metric]
        for (let h = 0; h < frames.length; h++) {
          const v = frames[h][p]
          if (v !== null && v !== undefined) properties[propertyName(metric, h)] = toWeight(metric, v)
        }
      }
      return { type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties }
    }),
  }
}

export function toWeight(metric: HeatmapMetric, value: number): number {
  return Math.round(((severityIndex(metric, value) + 1) / 5) * 1000) / 1000
}

/** Weight at a fractional hour: a linear blend of the two neighbouring hourly frames. */
export function weightExpression(metric: HeatmapMetric, hour: number, maxHour: number): ExpressionSpecification {
  const h0 = Math.max(0, Math.min(maxHour, Math.floor(hour)))
  const h1 = Math.min(maxHour, h0 + 1)
  const t = Math.round((hour - h0) * 1000) / 1000
  const at = (h: number): ExpressionSpecification => ['coalesce', ['get', propertyName(metric, h)], 0]
  if (t === 0 || h0 === h1) return at(h0)
  return ['+', ['*', 1 - t, at(h0)], ['*', t, at(h1)]]
}

const hexToRgba = (hex: string, alpha: number) => {
  const n = Number.parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** Density -> color. Stops sit at the weights of each risk level: 0.2, 0.4, ... 1.0. */
export const HEATMAP_COLOR: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['heatmap-density'],
  0,
  'rgba(0, 0, 0, 0)',
  0.1,
  hexToRgba(RISK_COLOR.low, 0.05),
  0.2,
  hexToRgba(RISK_COLOR.low, 0.22),
  0.4,
  hexToRgba(RISK_COLOR.moderate, 0.5),
  0.6,
  hexToRgba(RISK_COLOR.high, 0.58),
  0.8,
  hexToRgba(RISK_COLOR.severe, 0.62),
  1,
  hexToRgba(RISK_COLOR.no_travel, 0.66),
]

/**
 * Heatmap radius and intensity that turn the summed Gaussian kernels of a regular grid back
 * into the grid's values (density ~= weight), at every zoom.
 *
 * MapLibre's kernel is weight * intensity * (1/sqrt(2*pi)) * exp(-4.5 d^2 / r^2), i.e. a
 * Gaussian with sigma = r/3. Summed over a grid with spacing sx * sy pixels that is about
 * weight * intensity * 0.3989 * 2*pi*(r/3)^2 / (sx*sy). Radius scales with 2^zoom like the
 * grid itself, so one intensity works at every zoom.
 */
export function heatmapGeometry(stepDeg: number, meanLat: number) {
  const pxPerDegAtZ0 = 512 / 360
  const sx = stepDeg * pxPerDegAtZ0
  const sy = sx / Math.cos((meanLat * Math.PI) / 180)
  const radiusZ0 = 1.6 * sx
  const intensity = (sx * sy) / (0.3989 * 2 * Math.PI * (radiusZ0 / 3) ** 2)
  const radius: ExpressionSpecification = ['interpolate', ['exponential', 2], ['zoom'], 0, radiusZ0, 12, radiusZ0 * 2 ** 12]
  return { radius, intensity }
}
