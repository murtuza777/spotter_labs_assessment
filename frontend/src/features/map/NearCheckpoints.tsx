import { useEffect, useMemo, useRef } from 'react'
import { useMap } from 'react-map-gl/maplibre'
import type { TripPlan } from '../../api/types'
import { useTripStore } from '../../store/tripStore'
import { checkpointFeatureId } from './layers'

const WINDOW_H = 0.5

/** Flags checkpoints of the selected route whose ETA is near the slider time (feature-state). */
export function NearCheckpoints({ plan, selectedId }: { plan: TripPlan; selectedId: string }) {
  const { current: map } = useMap()
  const hour = useTripStore((s) => s.hour)
  const flagged = useRef<Set<number>>(new Set())

  const etas = useMemo(() => {
    const departure = Date.parse(plan.request.departure_time)
    const routeIndex = plan.routes.findIndex((r) => r.id === selectedId)
    const route = plan.routes[routeIndex]
    if (!route) return []
    return route.checkpoints.map((cp) => ({
      id: checkpointFeatureId(routeIndex, cp.index),
      h: (Date.parse(cp.eta) - departure) / 3_600_000,
    }))
  }, [plan, selectedId])

  useEffect(() => {
    if (!map || !map.getSource('checkpoints')) return
    const next = new Set(etas.filter((e) => Math.abs(e.h - hour) < WINDOW_H).map((e) => e.id))
    for (const id of flagged.current)
      if (!next.has(id)) map.setFeatureState({ source: 'checkpoints', id }, { near: false })
    for (const id of next)
      if (!flagged.current.has(id)) map.setFeatureState({ source: 'checkpoints', id }, { near: true })
    flagged.current = next
  }, [map, etas, hour])

  // A new plan or route replaces the features; forget what was flagged.
  useEffect(() => {
    const ids = flagged.current
    return () => {
      if (map?.getSource('checkpoints')) for (const id of ids) map.setFeatureState({ source: 'checkpoints', id }, { near: false })
      flagged.current = new Set()
    }
  }, [map, etas])

  return null
}
