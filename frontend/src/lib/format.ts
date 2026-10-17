import { format } from 'date-fns'

export function formatMiles(mi: number): string {
  return `${mi.toLocaleString(undefined, { maximumFractionDigits: mi < 10 ? 1 : 0 })} mi`
}

export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60)
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}

export function formatClock(iso: string | Date): string {
  return format(typeof iso === 'string' ? new Date(iso) : iso, 'EEE h:mm a')
}

export function formatDateTime(iso: string | Date): string {
  return format(typeof iso === 'string' ? new Date(iso) : iso, 'EEE MMM d, h:mm a')
}

export function formatWeight(lb: number): string {
  return `${lb.toLocaleString()} lb`
}

/** Value for <input type="datetime-local"> in the browser's timezone. */
export function toLocalInputValue(date: Date): string {
  return format(date, "yyyy-MM-dd'T'HH:mm")
}

export function nextWholeHour(now = new Date()): Date {
  const d = new Date(now)
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return d
}

export function localTimezoneName(): string {
  return new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
    .formatToParts(new Date())
    .find((p) => p.type === 'timeZoneName')?.value ?? ''
}
