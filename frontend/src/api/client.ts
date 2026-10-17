import type { ApiErrorBody, HeatmapResponse, Place, PlanRequest, TripPlan } from './types'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: Record<string, unknown>

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

// Empty in dev (Vite proxies /api). In production, the Render API origin, e.g.
// VITE_API_BASE_URL=https://murtuza-truck-routing-api.onrender.com (set in render.yaml)
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network', 'Could not reach the server. Check your connection.')
  }
  if (!response.ok) {
    let body: Partial<ApiErrorBody> = {}
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      // non-JSON error page (e.g. a proxy timeout)
    }
    const error = body.error
    throw new ApiError(
      response.status,
      error?.code ?? 'http_error',
      error?.message ?? `Request failed (${response.status}).`,
      error?.details,
    )
  }
  return (await response.json()) as T
}

export function fetchHealth(): Promise<{ status: string }> {
  return requestJson('/api/health/')
}

export async function searchPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  const data = await requestJson<{ results: Place[] }>(
    `/api/geocode/?q=${encodeURIComponent(query)}`,
    { signal },
  )
  return data.results
}

export function planTrip(body: PlanRequest): Promise<TripPlan> {
  return requestJson('/api/plan/', { method: 'POST', body: JSON.stringify(body) })
}

export function fetchHeatmap(plan: TripPlan, signal?: AbortSignal): Promise<HeatmapResponse> {
  return requestJson('/api/heatmap/', {
    method: 'POST',
    signal,
    body: JSON.stringify({
      routes: plan.routes.map((r) => r.geometry),
      departure_time: plan.request.departure_time,
      load_weight_lb: plan.request.load_weight_lb,
      wind_metric: plan.request.wind_metric,
    }),
  })
}
