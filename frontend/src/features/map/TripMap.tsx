import 'maplibre-gl/dist/maplibre-gl.css'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Map, { Marker, ScaleControl, type MapLayerMouseEvent, type MapRef } from 'react-map-gl/maplibre'
import type { HeatmapResponse, TripPlan } from '../../api/types'
import { FitIcon, Spinner } from '../../components/icons'
import { boundsOf, decodePolyline } from '../../lib/geo'
import { prefersReducedMotion, useMediaQuery, WIDE_LAYOUT } from '../../lib/media'
import { buildRouteModels, defaultRouteId, type RouteModel } from '../../lib/routeModel'
import { useTripStore } from '../../store/tripStore'
import { CheckpointDetails } from './CheckpointDetails'
import { CheckpointPopup } from './CheckpointPopup'
import { FocusedCheckpoint } from './FocusedCheckpoint'
import { HeatmapLayer } from './HeatmapLayer'
import './maplibre'
import { NearCheckpoints } from './NearCheckpoints'
import { CHECKPOINT_LAYER, ROUTE_HIT_LAYER, ROUTES_BOTTOM_LAYER, RouteLayers } from './RouteLayers'
import { TruckMarker } from './TruckMarker'

// OpenFreeMap: free vector basemap, no API key.
const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
const CONTINENTAL_US = { longitude: -98.5, latitude: 39.8, zoom: 3.6 }
const INTERACTIVE = [CHECKPOINT_LAYER, ROUTE_HIT_LAYER]
// Below this map size a floating popup can't always fit beside its point; dock it instead.
const DOCK_BELOW = { width: 560, height: 520 }

interface Props {
  plan: TripPlan | undefined
  heatmap: HeatmapResponse | undefined
  /** A plan request is in flight. */
  pending?: boolean
}

interface Hovered {
  routeId: string
  index: number
}

/** The map container's size, tracked across panel changes, rotation and window resizes. */
function useElementSize(ref: React.RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize((s) => (s.width === Math.round(width) && s.height === Math.round(height) ? s : { width: Math.round(width), height: Math.round(height) }))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return size
}

export default function TripMap({ plan, heatmap, pending = false }: Props) {
  const mapRef = useRef<MapRef>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const size = useElementSize(boxRef)
  const [loaded, setLoaded] = useState(false)
  const [hovered, setHovered] = useState<Hovered | null>(null)
  const [cursor, setCursor] = useState('')
  const selectRoute = useTripStore((s) => s.selectRoute)
  const hoverRoute = useTripStore((s) => s.hoverRoute)
  const focusCheckpoint = useTripStore((s) => s.focusCheckpoint)
  const focused = useTripStore((s) => s.focused)
  const selectedId = useTripStore((s) => s.selectedRouteId) ?? (plan ? defaultRouteId(plan) : undefined)

  // Hover previews only where a mouse can hover; touch users tap for details.
  const canHover = useMediaQuery('(hover: hover) and (pointer: fine)')
  const coarse = useMediaQuery('(pointer: coarse)')
  const wide = useMediaQuery(WIDE_LAYOUT)
  const docked = size.width > 0 && (size.width < DOCK_BELOW.width || size.height < DOCK_BELOW.height)
  // Wide but short maps (phone landscape) dock details beside the point; narrow ones below it.
  const dockSide = docked && size.width >= DOCK_BELOW.width
  const sideWidth = Math.min(352, Math.round(size.width * 0.5))

  const models = useMemo<RouteModel[]>(() => (plan ? buildRouteModels(plan) : []), [plan])
  const selectedModel = models.find((m) => m.route.id === selectedId)

  const fitRoutes = useCallback(() => {
    const map = mapRef.current
    if (!map || !plan) return
    const bounds = boundsOf(plan.routes.map((r) => decodePolyline(r.geometry)))
    if (!bounds) return
    const { width, height } = map.getContainer().getBoundingClientRect()
    const pad = Math.round(Math.max(24, Math.min(64, Math.min(width, height) * 0.1)))
    map.fitBounds(bounds, { padding: { top: pad, bottom: pad, left: pad, right: pad + 44 }, duration: prefersReducedMotion() ? 0 : 900 })
  }, [plan])

  // Frame every route whenever a new plan arrives.
  useEffect(() => {
    if (loaded) fitRoutes()
  }, [fitRoutes, loaded])

  // In the single-column phone/tablet layout the map sits in a scrolling page: on touch
  // screens one finger scrolls the page and two move the map, so the map never traps scroll.
  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map || !loaded) return
    if (coarse && !wide) map.cooperativeGestures.enable()
    else map.cooperativeGestures.disable()
  }, [coarse, wide, loaded])

  // Bring a checkpoint picked from the list (or the map) into view, leaving room for docked
  // details. One already in view stays put, so the map doesn't jump under the user's finger.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !plan || !focused) return
    const cp = plan.routes.find((r) => r.id === focused.routeId)?.checkpoints[focused.index]
    if (!cp) return
    const box = boxRef.current?.getBoundingClientRect()
    if (!wide && box && (box.top < 0 || box.bottom > window.innerHeight))
      boxRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' })
    const { width, height } = map.getContainer().getBoundingClientRect()
    // The part of the map the docked details leave uncovered.
    // (The side dock sits on the left, clear of the zoom buttons.)
    const free = !docked
      ? { left: 0, bottom: height }
      : dockSide
        ? { left: sideWidth + 16, bottom: height }
        : { left: 0, bottom: height * 0.4 }
    const p = map.project([cp.lon, cp.lat])
    if (p.x >= free.left + 12 && p.x <= width - 12 && p.y >= 12 && p.y <= free.bottom - 12) return
    map.flyTo({
      center: [cp.lon, cp.lat],
      zoom: Math.max(map.getZoom(), 7.5),
      padding: { top: 0, right: 0, left: Math.round(free.left), bottom: Math.round(height - free.bottom) },
      duration: prefersReducedMotion() ? 0 : 800,
    })
  }, [focused, plan, docked, dockSide, sideWidth, wide])

  // Escape closes checkpoint details (opened or hover preview), wherever focus is.
  const hasDetails = !!focused || !!hovered
  useEffect(() => {
    if (!hasDetails) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setHovered(null)
      focusCheckpoint(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [hasDetails, focusCheckpoint])

  const onMouseMove = useCallback(
    (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0]
      const props = feature?.properties as { routeId?: string; index?: number } | undefined
      if (feature?.layer.id === CHECKPOINT_LAYER && props?.routeId !== undefined) {
        if (canHover && !docked) setHovered({ routeId: props.routeId, index: Number(props.index) })
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
    [hoverRoute, selectedId, canHover, docked],
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

  const target = focused ?? hovered
  const targetRoute = plan?.routes.find((r) => r.id === target?.routeId)
  const targetCheckpoint = target ? targetRoute?.checkpoints[target.index] : undefined
  const detailProps =
    targetRoute && targetCheckpoint && plan
      ? {
          route: targetRoute,
          checkpoint: targetCheckpoint,
          loadLb: plan.request.load_weight_lb,
          windMetric: plan.request.wind_metric,
          onClose: () => {
            // Hand focus back to the list row that opened these details, if there is one.
            const row = target && document.querySelector<HTMLElement>(`[data-checkpoint-row="${target.routeId}-${target.index}"]`)
            setHovered(null)
            focusCheckpoint(null)
            row?.focus({ preventScroll: true })
          },
        }
      : null

  const origin = plan?.request.origin
  const destination = plan?.request.destination
  const focusedRouteIndex = focused ? plan?.routes.findIndex((r) => r.id === focused.routeId) ?? -1 : -1

  return (
    <div ref={boxRef} className="relative h-full w-full">
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
          setLoaded(true)
          if (import.meta.env.DEV) (window as unknown as { __map: unknown }).__map = e.target
        }}
        dragRotate={false}
        touchPitch={false}
        maxPitch={0}
      >
        <ScaleControl position="bottom-left" unit="imperial" />

        {plan && <RouteLayers plan={plan} />}
        {plan && selectedId && <NearCheckpoints plan={plan} selectedId={selectedId} />}
        {plan && focused && focusedRouteIndex >= 0 && (
          <FocusedCheckpoint routeIndex={focusedRouteIndex} index={focused.index} />
        )}
        {plan && heatmap && <HeatmapLayer data={heatmap} beforeId={ROUTES_BOTTOM_LAYER} />}

        {origin && (
          <Marker longitude={origin.lon} latitude={origin.lat} anchor="center">
            <EndpointDot label="Start" tone="bg-slate-900" />
          </Marker>
        )}
        {destination && (
          <Marker longitude={destination.lon} latitude={destination.lat} anchor="center">
            <EndpointDot label="End" tone="bg-brand-600" />
          </Marker>
        )}
        {plan?.routes
          .filter((r) => r.waypoint)
          .map((r) => (
            <Marker key={`wp-${r.id}`} longitude={r.waypoint!.lon} latitude={r.waypoint!.lat} anchor="center">
              <span
                title={`Route ${r.id} is TomTom truck routing through this waypoint, placed by the app`}
                className="rounded border border-amber-400 bg-amber-50 px-1.5 py-0.5 text-xs font-semibold text-amber-900 shadow"
              >
                Waypoint · {r.id}
              </span>
            </Marker>
          ))}
        {selectedModel && <TruckMarker model={selectedModel} />}

        {detailProps && !docked && <CheckpointPopup {...detailProps} />}
      </Map>

      <MapToolbar mapRef={mapRef} onFit={plan ? fitRoutes : undefined} />

      {detailProps && docked && focused && (
        <section
          aria-label="Checkpoint details"
          style={dockSide ? { width: sideWidth } : undefined}
          className={`absolute z-20 overflow-y-auto overscroll-contain rounded-lg border border-slate-200 bg-white px-3 pt-2 pb-3 shadow-lg ${
            dockSide ? 'top-2 bottom-2 left-2' : 'inset-x-2 bottom-2 max-h-[min(58%,26rem)]'
          }`}
        >
          <CheckpointDetails {...detailProps} />
        </section>
      )}

      {!plan && !pending && (
        <p className="pointer-events-none absolute inset-x-4 top-1/2 mx-auto max-w-xs -translate-y-1/2 rounded-lg border border-slate-200 bg-white/95 px-4 py-3 text-center text-sm text-slate-600 shadow-sm">
          Plan a trip to see its routes, checkpoints and forecast here.
        </p>
      )}
      {pending && (
        <p
          className="pointer-events-none absolute top-3 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm"
          aria-hidden="true"
        >
          <Spinner className="h-4 w-4 text-brand-600" />
          Planning routes…
        </p>
      )}
    </div>
  )
}

/** Zoom and "show all routes", as 40 px labelled buttons (the stock control is 29 px). */
function MapToolbar({ mapRef, onFit }: { mapRef: React.RefObject<MapRef | null>; onFit?: () => void }) {
  const btn =
    'flex h-10 w-10 items-center justify-center text-slate-700 transition hover:bg-slate-100 active:bg-slate-200 disabled:opacity-40'
  const zoom = (delta: number) => mapRef.current?.zoomTo((mapRef.current?.getZoom() ?? 0) + delta, { duration: prefersReducedMotion() ? 0 : 250 })
  return (
    <div className="absolute top-3 right-3 z-10 flex flex-col gap-2">
      <div className="flex flex-col divide-y divide-slate-200 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
        <button type="button" className={btn} aria-label="Zoom in" onClick={() => zoom(1)}>
          <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
        <button type="button" className={btn} aria-label="Zoom out" onClick={() => zoom(-1)}>
          <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M5 12h14" />
          </svg>
        </button>
      </div>
      {onFit && (
        <button
          type="button"
          onClick={onFit}
          aria-label="Show all routes"
          title="Show all routes"
          className={`${btn} rounded-md border border-slate-200 bg-white shadow-sm`}
        >
          <FitIcon className="h-5 w-5" />
        </button>
      )}
    </div>
  )
}

function EndpointDot({ label, tone }: { label: string; tone: string }) {
  return (
    <span className={`rounded-full border-2 border-white px-2 py-0.5 text-xs font-bold text-white shadow ${tone}`}>{label}</span>
  )
}
