import type { ExpressionSpecification } from 'maplibre-gl'
import { memo, useMemo } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import type { TripPlan } from '../../api/types'
import { defaultRouteId } from '../../lib/routeModel'
import { useTripStore } from '../../store/tripStore'
import { UNKNOWN_COLOR } from '../../lib/risk'
import { LEVEL_COLOR_EXPR, checkpointsGeoJSON, routesGeoJSON, segmentsGeoJSON } from './layers'

export const ROUTE_HIT_LAYER = 'route-hit'
export const CHECKPOINT_LAYER = 'checkpoints'
export const ROUTES_BOTTOM_LAYER = 'route-inactive-casing'

/** Route lines, risk-colored segments of the selected route, and its checkpoints. */
export const RouteLayers = memo(function RouteLayers({ plan }: { plan: TripPlan }) {
  const routes = useMemo(() => routesGeoJSON(plan), [plan])
  const segments = useMemo(() => segmentsGeoJSON(plan), [plan])
  const checkpoints = useMemo(() => checkpointsGeoJSON(plan), [plan])

  const selected = useTripStore((s) => s.selectedRouteId) ?? defaultRouteId(plan)
  const hovered = useTripStore((s) => s.hoveredRouteId)

  const isSelected: ExpressionSpecification = ['==', ['get', 'routeId'], selected]
  const notSelected: ExpressionSpecification = ['!=', ['get', 'routeId'], selected]
  const isHovered: ExpressionSpecification = ['==', ['get', 'routeId'], hovered ?? '']

  return (
    <>
      <Source id="routes" type="geojson" data={routes}>
        <Layer
          id={ROUTES_BOTTOM_LAYER}
          type="line"
          filter={notSelected}
          layout={{ 'line-cap': 'round', 'line-join': 'round' }}
          paint={{ 'line-color': '#ffffff', 'line-width': ['case', isHovered, 9, 7] }}
        />
        <Layer
          id="route-inactive"
          type="line"
          filter={notSelected}
          layout={{ 'line-cap': 'round', 'line-join': 'round' }}
          paint={{
            'line-color': ['case', isHovered, '#0369a1', '#64748b'],
            'line-width': ['case', isHovered, 5, 3.5],
            'line-opacity': ['case', isHovered, 0.95, 0.7],
          }}
        />
        <Layer
          id="route-selected-casing"
          type="line"
          filter={isSelected}
          layout={{ 'line-cap': 'round', 'line-join': 'round' }}
          paint={{ 'line-color': '#0f172a', 'line-width': 9 }}
        />
        <Layer
          id={ROUTE_HIT_LAYER}
          type="line"
          layout={{ 'line-cap': 'round', 'line-join': 'round' }}
          paint={{ 'line-color': '#000000', 'line-width': 16, 'line-opacity': 0 }}
        />
      </Source>
      <Source id="segments" type="geojson" data={segments}>
        <Layer
          id="route-selected-risk"
          type="line"
          filter={['all', isSelected, ['!=', ['get', 'level'], 'unknown']]}
          layout={{ 'line-cap': 'round', 'line-join': 'round' }}
          paint={{ 'line-color': LEVEL_COLOR_EXPR, 'line-width': 5.5 }}
        />
        {/* Stretches with no forecast: dashed grey, so they can't be read as any risk level. */}
        <Layer
          id="route-selected-unknown"
          type="line"
          filter={['all', isSelected, ['==', ['get', 'level'], 'unknown']]}
          layout={{ 'line-join': 'round' }}
          paint={{ 'line-color': '#ffffff', 'line-width': 5.5 }}
        />
        <Layer
          id="route-selected-unknown-dash"
          type="line"
          filter={['all', isSelected, ['==', ['get', 'level'], 'unknown']]}
          layout={{ 'line-join': 'round' }}
          paint={{ 'line-color': UNKNOWN_COLOR, 'line-width': 5.5, 'line-dasharray': [1.2, 1] }}
        />
      </Source>
      <Source id="checkpoints" type="geojson" data={checkpoints} />
      <CheckpointLayer selected={selected} />
    </>
  )
})

/**
 * Checkpoints of the selected route. The ones whose ETA is within half an hour of the slider
 * get a thick ring through feature-state (set by NearCheckpoints), which unlike a data-driven
 * paint expression does not make MapLibre re-tile the source on every slider frame. The one
 * whose details are open (FocusedCheckpoint) is larger still. Checkpoints without a forecast
 * are hollow grey rings, never a filled dot, so they can't be mistaken for Low.
 */
function CheckpointLayer({ selected }: { selected: string }) {
  const near: ExpressionSpecification = ['boolean', ['feature-state', 'near'], false]
  const focused: ExpressionSpecification = ['boolean', ['feature-state', 'focused'], false]
  const unknown: ExpressionSpecification = ['==', ['get', 'level'], 'unknown']
  return (
    <Layer
      id={CHECKPOINT_LAYER}
      // Not a direct child of <Source>, so react-map-gl can't inject the source id.
      source="checkpoints"
      type="circle"
      filter={['==', ['get', 'routeId'], selected]}
      paint={{
        'circle-color': ['case', unknown, '#ffffff', LEVEL_COLOR_EXPR],
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          4,
          ['case', focused, 8, near, 6, 3.5],
          10,
          ['case', focused, 12, near, 10, 7],
        ],
        'circle-stroke-color': ['case', focused, '#1f459f', near, '#0f172a', unknown, UNKNOWN_COLOR, '#ffffff'],
        'circle-stroke-width': ['case', focused, 3, near, 2.5, unknown, 2.5, 1.5],
      }}
    />
  )
}
