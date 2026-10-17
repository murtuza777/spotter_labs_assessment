import type { Place } from '../../api/types'

export interface Preset {
  name: string
  origin: Place
  destination: Place
  load: number
}

export const PRESETS: Preset[] = [
  {
    name: 'Denver → Salt Lake City',
    origin: { label: 'Denver, Colorado, US', lat: 39.7392, lon: -104.9903 },
    destination: { label: 'Salt Lake City, Utah, US', lat: 40.7608, lon: -111.891 },
    load: 36_000,
  },
  {
    name: 'Seattle → Spokane',
    origin: { label: 'Seattle, Washington, US', lat: 47.6062, lon: -122.3321 },
    destination: { label: 'Spokane, Washington, US', lat: 47.6588, lon: -117.426 },
    load: 42_000,
  },
  {
    name: 'Chicago → Minneapolis',
    origin: { label: 'Chicago, Illinois, US', lat: 41.8781, lon: -87.6298 },
    destination: { label: 'Minneapolis, Minnesota, US', lat: 44.9778, lon: -93.265 },
    load: 28_000,
  },
]
