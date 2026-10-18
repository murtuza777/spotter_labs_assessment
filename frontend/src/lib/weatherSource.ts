import type { WeatherField } from '../api/types'

/** Display names for the backend's weather provider ids. */
export const PROVIDER_NAMES: Record<string, string> = {
  weatherapi: 'WeatherAPI.com',
  nws: 'National Weather Service',
  'open-meteo': 'Open-Meteo',
}

const FIELD_LABELS: Record<WeatherField, string> = {
  wind_mph: 'wind',
  gust_mph: 'gusts',
  rain_in_hr: 'rain',
  snow_in_hr: 'snow',
}

const providerName = (id: string) => PROVIDER_NAMES[id] ?? id

/**
 * Where a checkpoint's readings came from, e.g. "WeatherAPI.com", or
 * "WeatherAPI.com; gusts from National Weather Service" when a fallback filled a gap.
 */
export function describeWeatherSource(source: Partial<Record<WeatherField, string>> | null | undefined): string | null {
  if (!source) return null
  const fields = (Object.keys(FIELD_LABELS) as WeatherField[]).filter((f) => source[f])
  if (!fields.length) return null
  const counts = new Map<string, number>()
  for (const f of fields) counts.set(source[f]!, (counts.get(source[f]!) ?? 0) + 1)
  // The provider behind most readings leads; ties go to the one listed first.
  const primary = [...counts.entries()].reduce((a, b) => (b[1] > a[1] ? b : a))[0]
  const others = new Map<string, string[]>()
  for (const f of fields) {
    const p = source[f]!
    if (p !== primary) others.set(p, [...(others.get(p) ?? []), FIELD_LABELS[f]])
  }
  const extra = [...others.entries()].map(([p, labels]) => `${labels.join(' and ')} from ${providerName(p)}`)
  return [providerName(primary), ...extra].join('; ')
}
