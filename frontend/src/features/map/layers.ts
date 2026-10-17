import type { ExpressionSpecification } from 'maplibre-gl'
import type { FeatureCollection, LineString, Point } from 'geojson'
import type { TripPlan } from '../../api/types'
import { decodePolyline } from '../../lib/geo'
import { RISK_COLOR, UNKNOWN_COLOR } from '../../lib/risk'

export const LEVEL_COLOR_EXPR: ExpressionSpecification = [
  'match',
  ['get', 'level'],
  'low',
  RISK_COLOR.low,
  'moderate',
  RISK_COLOR.moderate,
  'high',
  RISK_COLOR.high,
  'severe',
  RISK_COLOR.severe,
  'no_travel',
  RISK_COLOR.no_travel,
  UNKNOWN_COLOR,
]

export function routesGeoJSON(plan: TripPlan): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: plan.routes.map((r) => ({
      type: 'Feature',
      properties: { routeId: r.id },
      geometry: { type: 'LineString', coordinates: decodePolyline(r.geometry) },
    })),
  }
}

export function segmentsGeoJSON(plan: TripPlan): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: plan.routes.flatMap((r) =>
      r.segments.map((s) => ({
        type: 'Feature' as const,
        properties: { routeId: r.id, level: s.level ?? 'unknown' },
        geometry: { type: 'LineString' as const, coordinates: decodePolyline(s.geometry) },
      })),
    ),
  }
}

export function checkpointsGeoJSON(plan: TripPlan): FeatureCollection<Point> {
  const departure = Date.parse(plan.request.departure_time)
  return {
    type: 'FeatureCollection',
    features: plan.routes.flatMap((r) =>
      r.checkpoints.map((cp) => ({
        type: 'Feature' as const,
        id: `${r.id}-${cp.index}`,
        properties: {
          routeId: r.id,
          index: cp.index,
          level: cp.risk?.level ?? 'unknown',
          etaH: (Date.parse(cp.eta) - departure) / 3_600_000,
        },
        geometry: { type: 'Point' as const, coordinates: [cp.lon, cp.lat] },
      })),
    ),
  }
}
