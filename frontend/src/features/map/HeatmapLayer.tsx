import { memo, useEffect, useMemo, useState } from 'react'
import { Layer, Source, useMap } from 'react-map-gl/maplibre'
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
  const anchorReady = useLayerExists(beforeId)

  // The frames are inserted below the route layers. If the heatmap arrives before those exist
  // (e.g. a cached heatmap right after a new plan), MapLibre would reject every frame, so wait.
  if (!anchorReady) return null

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
      {/* After the frames, so the dots sit above the heatmap but below the routes. */}
      {Array.from({ length: hours }, (_, h) => (
        <UnknownCellsLayer key={`u${h}`} hour={h} maxHour={hours - 1} metric={metric} beforeId={beforeId} />
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

/**
 * Grey dots where this hour has no forecast for the selected metric, so missing data is shown
 * as missing instead of as an untinted (calm-looking) gap. Like the heatmap frames, these are
 * built once and only their opacity follows the slider (nearest hour).
 */
function UnknownCellsLayer({
  hour,
  maxHour,
  metric,
  beforeId,
}: {
  hour: number
  maxHour: number
  metric: HeatmapMetric
  beforeId?: string
}) {
  const shown = useTripStore((s) => s.heatmapVisible && Math.round(Math.max(0, Math.min(maxHour, s.hour))) === hour)
  const opacity = shown ? 0.9 : 0
  return (
    <Layer
      id={`weather-unknown-${hour}`}
      type="circle"
      beforeId={beforeId}
      source="heatmap"
      filter={['!', ['has', propertyName(metric, hour)]]}
      paint={{
        'circle-color': '#94a3b8',
        'circle-radius': 3.5,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1,
        'circle-opacity': opacity,
        'circle-stroke-opacity': opacity,
        'circle-opacity-transition': NO_TRANSITION,
        'circle-stroke-opacity-transition': NO_TRANSITION,
      }}
    />
  )
}

/** Whether a style layer exists yet; re-checked on every style change until it does. */
function useLayerExists(layerId: string | undefined): boolean {
  const { current: map } = useMap()
  const [exists, setExists] = useState(() => !layerId || !!map?.getLayer(layerId))
  useEffect(() => {
    if (!map || !layerId || exists) return
    const check = () => {
      if (map.getLayer(layerId)) setExists(true)
    }
    map.on('styledata', check)
    // The layer may have been added between render and this effect.
    const id = requestAnimationFrame(check)
    return () => {
      map.off('styledata', check)
      cancelAnimationFrame(id)
    }
  }, [map, layerId, exists])
  return exists
}
