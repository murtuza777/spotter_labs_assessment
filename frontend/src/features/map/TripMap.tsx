import 'maplibre-gl/dist/maplibre-gl.css'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Map, {
  Marker,
  NavigationControl,
  ScaleControl,
  type MapLayerMouseEvent,
  type MapRef,
} from 'react-map-gl/maplibre'
import type { HeatmapResponse, TripPlan } from '../../api/types'
import { boundsOf, decodePolyline } from '../../lib/geo'
import { buildRouteModels, type RouteModel } from '../../lib/routeModel'
import { useTripStore } from '../../store/tripStore'
import { CheckpointPopup } from './CheckpointPopup'
import { HeatmapLayer } from './HeatmapLayer'
import { Legend } from './Legend'
import './maplibre'
import { CHECKPOINT_LAYER, ROUTE_HIT_LAYER, ROUTES_BOTTOM_LAYER, RouteLayers } from './RouteLayers'
import { TruckMarker } from './TruckMarker'

// OpenFreeMap: free vector basemap, no API key.
const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
const CONTINENTAL_US = { longitude: -98.5, latitude: 39.8, zoom: 3.6 }
const INTERACTIVE = [CHECKPOINT_LAYER, ROUTE_HIT_LAYER]

interface Props {
  plan: TripPlan | undefined
  heatmap: HeatmapResponse | undefined
}

interface Hovered {
  routeId: string
  index: number
}

export default function TripMap({ plan, heatmap }: Props) {
  const mapRef = useRef<MapRef>(null)
  const [hovered, setHovered] = useState<Hovered | null>(null)
  const [cursor, setCursor] = useState('')
  const selectRoute = useTripStore((s) => s.selectRoute)
  const hoverRoute = useTripStore((s) => s.hoverRoute)
  const focusCheckpoint = useTripStore((s) => s.focusCheckpoint)
  const focused = useTripStore((s) => s.focused)
  const selectedId = useTripStore((s) => s.selectedRouteId) ?? plan?.recommended_route_id

  const models = useMemo<RouteModel[]>(() => (plan ? buildRouteModels(plan) : []), [plan])
  const selectedModel = models.find((m) => m.route.id === selectedId)

  // Frame every route whenever a new plan arrives.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !plan) return
    const bounds = boundsOf(plan.routes.map((r) => decodePolyline(r.geometry)))
    if (bounds) map.fitBounds(bounds, { padding: { top: 70, bottom: 150, left: 50, right: 50 }, duration: 900 })
  }, [plan])

  // Fly to a checkpoint picked from the sidebar list.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !plan || !focused) return
    const cp = plan.routes.find((r) => r.id === focused.routeId)?.checkpoints[focused.index]
    if (cp) map.flyTo({ center: [cp.lon, cp.lat], zoom: Math.max(map.getZoom(), 7.5), duration: 800 })
  }, [focused, plan])

  const onMouseMove = useCallback(
    (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0]
      const props = feature?.properties as { routeId?: string; index?: number } | undefined
      if (feature?.layer.id === CHECKPOINT_LAYER && props?.routeId !== undefined) {
        setHovered({ routeId: props.routeId, index: Number(props.index) })
        hoverRoute(null)
        setCursor('pointer')
      } else if (feature?.layer.id === ROUTE_HIT_LAYER && props?.routeId) {
        setHovered(null)
        hoverRoute(props.routeId === selectedId ? null : props.routeId)
        setCursor('pointer')
      } else {
        setHovered(null)
        hoverRoute(null)
        setCursor('')
      }
    },
    [hoverRoute, selectedId],
  )

  const onClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0]
      const props = feature?.properties as { routeId?: string; index?: number } | undefined
      if (!props?.routeId) return focusCheckpoint(null)
      if (feature?.layer.id === CHECKPOINT_LAYER) focusCheckpoint({ routeId: props.routeId, index: Number(props.index) })
      else selectRoute(props.routeId)
    },
    [focusCheckpoint, selectRoute],
  )

  const popupTarget = hovered ?? focused
  const popupRoute = plan?.routes.find((r) => r.id === popupTarget?.routeId)
  const popupCheckpoint = popupTarget ? popupRoute?.checkpoints[popupTarget.index] : undefined

  const origin = plan?.request.origin
  const destination = plan?.request.destination

  return (
    <Map
      ref={mapRef}
      initialViewState={CONTINENTAL_US}
      mapStyle={BASEMAP_STYLE}
      style={{ width: '100%', height: '100%' }}
      interactiveLayerIds={plan ? INTERACTIVE : undefined}
      onMouseMove={onMouseMove}
      onMouseLeave={() => {
        setHovered(null)
        hoverRoute(null)
      }}
      onClick={onClick}
      cursor={cursor}
      onLoad={(e) => {
        if (import.meta.env.DEV) (window as unknown as { __map: unknown }).__map = e.target
      }}
      dragRotate={false}
      touchPitch={false}
      maxPitch={0}
    >
      <NavigationControl position="top-right" showCompass={false} />
      <ScaleControl position="bottom-right" unit="imperial" />

      {plan && <RouteLayers plan={plan} />}
      {plan && heatmap && <HeatmapLayer data={heatmap} beforeId={ROUTES_BOTTOM_LAYER} />}

      {origin && (
        <Marker longitude={origin.lon} latitude={origin.lat} anchor="center">
          <EndpointDot label="Start" tone="bg-slate-900" />
        </Marker>
      )}
      {destination && (
        <Marker longitude={destination.lon} latitude={destination.lat} anchor="center">
          <EndpointDot label="End" tone="bg-sky-600" />
        </Marker>
      )}
      {selectedModel && <TruckMarker model={selectedModel} />}

      {popupRoute && popupCheckpoint && plan && (
        <CheckpointPopup
          route={popupRoute}
          checkpoint={popupCheckpoint}
          loadLb={plan.request.load_weight_lb}
          onClose={() => focusCheckpoint(null)}
        />
      )}
      <Legend />
    </Map>
  )
}

function EndpointDot({ label, tone }: { label: string; tone: string }) {
  return (
    <span
      className={`rounded-full border-2 border-white px-1.5 py-0.5 text-[10px] font-bold text-white shadow ${tone}`}
    >
      {label}
    </span>
  )
}
