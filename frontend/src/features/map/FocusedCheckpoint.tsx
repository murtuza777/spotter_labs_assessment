import { useEffect } from 'react'
import { useMap } from 'react-map-gl/maplibre'
import { checkpointFeatureId } from './layers'

/** Rings the checkpoint whose details are open (feature-state, so nothing is re-uploaded). */
export function FocusedCheckpoint({ routeIndex, index }: { routeIndex: number; index: number }) {
  const { current: map } = useMap()
  useEffect(() => {
    if (!map || !map.getSource('checkpoints')) return
    const id = checkpointFeatureId(routeIndex, index)
    map.setFeatureState({ source: 'checkpoints', id }, { focused: true })
    return () => {
      if (map.getSource('checkpoints')) map.setFeatureState({ source: 'checkpoints', id }, { focused: false })
    }
  }, [map, routeIndex, index])
  return null
}
