import type { Checkpoint, PlannedRoute, TripPlan } from '../api/types'
import { cumulativeMiles, decodePolyline, interpolateAlong, interpolateSeries, type LngLat } from './geo'

/** Everything the map needs per route, decoded once per plan. */
export interface RouteModel {
  route: PlannedRoute
  coords: LngLat[]
  /** Along-route miles of each coord, scaled so the last equals route.distance_mi. */
  cum: number[]
  /** Hours since departure at each checkpoint, ascending. */
  checkpointHours: number[]
  checkpointMiles: number[]
  durationH: number
}

export function buildRouteModels(plan: TripPlan): RouteModel[] {
  const departure = Date.parse(plan.request.departure_time)
  return plan.routes.map((route) => {
    const coords = decodePolyline(route.geometry)
    const raw = cumulativeMiles(coords)
    const scale = raw[raw.length - 1] > 0 ? route.distance_mi / raw[raw.length - 1] : 1
    return {
      route,
      coords,
      cum: raw.map((m) => m * scale),
      checkpointHours: route.checkpoints.map((c) => (Date.parse(c.eta) - departure) / 3_600_000),
      checkpointMiles: route.checkpoints.map((c) => c.mile),
      durationH: route.duration_s / 3600,
    }
  })
}

export interface TruckStatus {
  mile: number
  arrived: boolean
  /** The checkpoint closest to the truck at that time (its weather is at its own ETA). */
  nearest: Checkpoint
}

/** Where the truck on `route` is `hours` after departure, and the checkpoint it is nearest. */
export function truckStatus(route: PlannedRoute, departureIso: string, hours: number): TruckStatus {
  const departure = Date.parse(departureIso)
  const cpHours = route.checkpoints.map((c) => (Date.parse(c.eta) - departure) / 3_600_000)
  const mile = interpolateSeries(
    cpHours,
    route.checkpoints.map((c) => c.mile),
    hours,
  )
  let nearest = route.checkpoints[0]
  for (const cp of route.checkpoints) if (Math.abs(cp.mile - mile) < Math.abs(nearest.mile - mile)) nearest = cp
  return { mile, arrived: hours >= route.duration_s / 3600, nearest }
}

/** Where the truck is `hours` after departure (clamped to the trip). */
export function truckPosition(model: RouteModel, hours: number): { at: LngLat; mile: number; arrived: boolean } {
  const mile = interpolateSeries(model.checkpointHours, model.checkpointMiles, hours)
  return {
    at: interpolateAlong(model.coords, model.cum, mile),
    mile,
    arrived: hours >= model.durationH,
  }
}
