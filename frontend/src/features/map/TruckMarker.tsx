import { Marker } from 'react-map-gl/maplibre'
import { truckPosition, type RouteModel } from '../../lib/routeModel'
import { useTripStore } from '../../store/tripStore'

/** The truck's position at the slider's time, moving with the checkpoint ETAs. */
export function TruckMarker({ model }: { model: RouteModel }) {
  const hour = useTripStore((s) => s.hour)
  const { at, arrived } = truckPosition(model, hour)
  return (
    <Marker longitude={at[0]} latitude={at[1]} anchor="center" style={{ zIndex: 5 }}>
      <div
        title={arrived ? 'Arrived' : `Truck position at departure +${hour.toFixed(1)} h`}
        className={`flex h-7 w-7 items-center justify-center rounded-full border-2 border-white shadow-lg ${
          arrived ? 'bg-emerald-600' : 'bg-slate-900'
        }`}
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4 fill-white" aria-hidden="true">
          <path d="M3 6h11v9H3zM14 9h4l3 3v3h-7zM6.5 18.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zm11 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z" />
        </svg>
      </div>
    </Marker>
  )
}
