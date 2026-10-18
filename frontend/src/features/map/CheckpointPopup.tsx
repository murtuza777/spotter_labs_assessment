import { Popup } from 'react-map-gl/maplibre'
import { CheckpointDetails, type CheckpointDetailsProps } from './CheckpointDetails'

// Keep the popup this far from the map's edges when MapLibre picks its anchor.
const EDGE = { top: 12, bottom: 12, left: 12, right: 12 }

/**
 * Checkpoint details anchored to the map point. No fixed anchor: MapLibre then picks the
 * side (top/bottom/left/right and corners) that keeps the popup inside the map container.
 * On maps too small for that, TripMap docks the same details inside the map instead.
 */
export function CheckpointPopup(props: CheckpointDetailsProps) {
  const { checkpoint: cp, onClose } = props
  return (
    <Popup
      longitude={cp.lon}
      latitude={cp.lat}
      offset={14}
      padding={EDGE}
      closeButton={false}
      closeOnClick={false}
      focusAfterOpen={false}
      onClose={onClose}
      maxWidth="20rem"
      className="checkpoint-popup"
    >
      <CheckpointDetails {...props} />
    </Popup>
  )
}
