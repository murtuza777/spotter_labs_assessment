import { create } from 'zustand'
import type { HeatmapMetric } from '../api/types'

export const MAX_HOUR = 48

interface FocusedCheckpoint {
  routeId: string
  index: number
}

interface TripState {
  selectedRouteId: string | null
  hoveredRouteId: string | null
  /** Hours after departure shown by the heatmap and truck marker (fractional while playing). */
  hour: number
  isPlaying: boolean
  heatmapMetric: HeatmapMetric
  heatmapVisible: boolean
  focused: FocusedCheckpoint | null

  selectRoute: (id: string | null) => void
  hoverRoute: (id: string | null) => void
  setHour: (hour: number) => void
  setPlaying: (playing: boolean) => void
  setHeatmapMetric: (metric: HeatmapMetric) => void
  toggleHeatmap: () => void
  focusCheckpoint: (focus: FocusedCheckpoint | null) => void
  resetForPlan: (recommendedId: string) => void
}

export const useTripStore = create<TripState>((set) => ({
  selectedRouteId: null,
  hoveredRouteId: null,
  hour: 0,
  isPlaying: false,
  heatmapMetric: 'risk',
  heatmapVisible: true,
  focused: null,

  selectRoute: (id) => set({ selectedRouteId: id, focused: null }),
  hoverRoute: (id) => set({ hoveredRouteId: id }),
  setHour: (hour) => set({ hour: Math.max(0, Math.min(MAX_HOUR, hour)) }),
  setPlaying: (isPlaying) => set({ isPlaying }),
  setHeatmapMetric: (heatmapMetric) => set({ heatmapMetric }),
  toggleHeatmap: () => set((s) => ({ heatmapVisible: !s.heatmapVisible })),
  focusCheckpoint: (focused) => set({ focused }),
  resetForPlan: (recommendedId) =>
    set({ selectedRouteId: recommendedId, hoveredRouteId: null, hour: 0, isPlaying: false, focused: null }),
}))
