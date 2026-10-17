import { memo, useMemo } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import type { HeatmapResponse } from '../../api/types'
import { HEATMAP_COLOR, buildHeatmapGeoJSON, heatmapGeometry, weightExpression } from '../../lib/heatmap'
import { useTripStore } from '../../store/tripStore'

export const HEATMAP_LAYER_ID = 'weather-heatmap'

/**
 * The GeoJSON (every metric, every hour) is uploaded once per heatmap response. Moving the
 * slider re-renders only this component and changes one paint property.
 */
export const HeatmapLayer = memo(function HeatmapLayer({ data, beforeId }: { data: HeatmapResponse; beforeId?: string }) {
  const geojson = useMemo(() => buildHeatmapGeoJSON(data), [data])
  const { radius, intensity } = useMemo(() => {
    const meanLat = data.points.reduce((sum, [lat]) => sum + lat, 0) / Math.max(1, data.points.length)
    return heatmapGeometry(data.grid_step_deg, meanLat)
  }, [data])

  const hour = useTripStore((s) => s.hour)
  const metric = useTripStore((s) => s.heatmapMetric)
  const visible = useTripStore((s) => s.heatmapVisible)
  const maxHour = data.hours.length - 1

  return (
    <Source id="heatmap" type="geojson" data={geojson}>
      <Layer
        id={HEATMAP_LAYER_ID}
        type="heatmap"
        beforeId={beforeId}
        maxzoom={10}
        layout={{ visibility: visible ? 'visible' : 'none' }}
        paint={{
          'heatmap-weight': weightExpression(metric, hour, maxHour),
          'heatmap-intensity': intensity,
          'heatmap-radius': radius,
          'heatmap-color': HEATMAP_COLOR,
          'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.9, 10, 0],
        }}
      />
    </Source>
  )
})
