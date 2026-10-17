import { memo, useMemo } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import type { HeatmapMetric, HeatmapResponse } from '../../api/types'
import { HEATMAP_COLOR, buildHeatmapGeoJSON, frameOpacities, heatmapGeometry, propertyName } from '../../lib/heatmap'
import { useTripStore } from '../../store/tripStore'

const heatmapLayerId = (hour: number) => `weather-heatmap-${hour}`
const MAX_OPACITY = 0.9
const NO_TRANSITION = { duration: 0, delay: 0 }

/**
 * One heatmap layer per forecast hour, all built once per response (and per metric).
 *
 * The slider only changes `heatmap-opacity`, cross-fading the two hours around the slider
 * position. Opacity is not data-driven, so MapLibre neither re-tiles the source nor
 * re-uploads anything, and layers at opacity 0 are skipped entirely when drawing. Changing
 * `heatmap-weight` (or visibility) per frame instead would reload the source every frame.
 */
export const HeatmapLayer = memo(function HeatmapLayer({ data, beforeId }: { data: HeatmapResponse; beforeId?: string }) {
  const geojson = useMemo(() => buildHeatmapGeoJSON(data), [data])
  const { radius, intensity } = useMemo(() => {
    const meanLat = data.points.reduce((sum, [lat]) => sum + lat, 0) / Math.max(1, data.points.length)
    return heatmapGeometry(data.grid_step_deg, meanLat)
  }, [data])

  const metric = useTripStore((s) => s.heatmapMetric)
  const hours = data.hours.length

  return (
    <Source id="heatmap" type="geojson" data={geojson}>
      {Array.from({ length: hours }, (_, h) => (
        <HourLayer
          key={h}
          hour={h}
          maxHour={hours - 1}
          metric={metric}
          radius={radius}
          intensity={intensity}
          beforeId={beforeId}
        />
      ))}
    </Source>
  )
})

interface HourLayerProps {
  hour: number
  maxHour: number
  metric: HeatmapMetric
  radius: ReturnType<typeof heatmapGeometry>['radius']
  intensity: number
  beforeId?: string
}

function HourLayer({ hour, maxHour, metric, radius, intensity, beforeId }: HourLayerProps) {
  // Subscribe to this layer's own opacity only, so a slider move re-renders at most the
  // few layers whose opacity actually changes.
  const opacity = useTripStore((s) => (s.heatmapVisible ? (frameOpacities(s.hour, maxHour)[hour] ?? 0) : 0))
  return (
    <Layer
      id={heatmapLayerId(hour)}
      type="heatmap"
      source="heatmap"
      beforeId={beforeId}
      maxzoom={10}
      paint={{
        'heatmap-weight': ['coalesce', ['get', propertyName(metric, hour)], 0],
        'heatmap-intensity': intensity,
        'heatmap-radius': radius,
        'heatmap-color': HEATMAP_COLOR,
        'heatmap-opacity': opacity * MAX_OPACITY,
        'heatmap-opacity-transition': NO_TRANSITION,
      }}
    />
  )
}
