// Mirrors the backend contract (docs/IMPLEMENTATION_PLAN.md section 4.3).

export type RiskLevel = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'
export type WindMetric = 'gust' | 'sustained'
export type SampleInterval = 10 | 25 | 50

export interface Place {
  label: string
  lat: number
  lon: number
}

export interface PlanRequest {
  origin: Place
  destination: Place
  departure_time: string
  load_weight_lb: number
  sample_interval_mi: SampleInterval
  wind_metric: WindMetric
}

export interface CheckpointWeather {
  wind_mph: number
  gust_mph: number
  rain_in_hr: number
  snow_in_hr: number
}

export interface Checkpoint {
  index: number
  mile: number
  lat: number
  lon: number
  eta: string
  forecast_hour: string
  weather: CheckpointWeather | null
  risk: { level: RiskLevel; score: number; reasons: string[] } | null
}

export interface RouteSummary {
  miles_by_level: Record<RiskLevel, number>
  unknown_miles: number
  avg_risk: number
  max_level: RiskLevel | null
}

export interface RiskSegment {
  level: RiskLevel | null
  start_mile: number
  end_mile: number
  geometry: string
}

export interface PlannedRoute {
  id: string
  source: 'routing_api' | 'detour'
  rank: number
  distance_mi: number
  duration_s: number
  arrival_time: string
  geometry: string
  summary: RouteSummary
  segments: RiskSegment[]
  checkpoints: Checkpoint[]
}

export interface WeatherStats {
  cells: number
  cached: number
  fetched: number
  failed: number
  ms: number
}

/** Request accounting from the backend: provider calls, weather cache use, timings. */
export interface PlanMeta {
  /** Calls into the (cached) routing layer; cache hits never reach TomTom. */
  routing_lookups: number
  routing_ms: number
  checkpoints: number
  weather: WeatherStats
  total_ms: number
}

export interface TripPlan {
  generated_at: string
  request: PlanRequest
  recommended_route_id: string
  recommendation: { reason: string; warnings: string[] }
  routes: PlannedRoute[]
  notices: string[]
  meta?: PlanMeta
}

export type HeatmapMetric = 'risk' | 'gust' | 'rain' | 'snow'

export interface HeatmapResponse {
  hours: string[]
  points: [number, number][] // [lat, lon]
  grid_step_deg: number
  levels: RiskLevel[]
  frames: Record<HeatmapMetric, (number | null)[][]> // [hour][point]
  meta?: { weather: WeatherStats; unknown_cells: number }
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}
