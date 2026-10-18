import { useSyncExternalStore } from 'react'

/** True while `query` matches; re-renders when it changes (resize, rotation, settings). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** The two-column workspace (panel + full-height map) starts at Tailwind's `lg`. */
export const WIDE_LAYOUT = '(min-width: 1024px)'
