import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { fetchHeatmap, planTrip, searchPlaces } from './client'
import type { TripPlan } from './types'

export function usePlaceSearch(query: string) {
  const q = query.trim()
  return useQuery({
    queryKey: ['places', q.toLowerCase()],
    queryFn: ({ signal }) => searchPlaces(q, signal),
    enabled: q.length >= 2,
    staleTime: 10 * 60_000,
    placeholderData: keepPreviousData,
  })
}

export function usePlanTrip() {
  return useMutation({ mutationFn: planTrip })
}

export function useHeatmap(plan: TripPlan | undefined) {
  return useQuery({
    queryKey: ['heatmap', plan?.generated_at, plan?.request],
    queryFn: ({ signal }) => fetchHeatmap(plan!, signal),
    enabled: !!plan,
    staleTime: 30 * 60_000,
    retry: 1,
  })
}
