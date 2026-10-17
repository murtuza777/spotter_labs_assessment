import { useState } from 'react'
import type { Place, PlanRequest, SampleInterval, WindMetric } from '../../api/types'
import { localTimezoneName, nextWholeHour, toLocalInputValue } from '../../lib/format'
import { PlaceAutocomplete } from './PlaceAutocomplete'
import { PRESETS, type Preset } from './presets'

const INTERVALS: SampleInterval[] = [10, 25, 50]
const MAX_LOAD_LB = 80_000

interface Props {
  onSubmit: (request: PlanRequest) => void
  isPending: boolean
  serverErrors?: Record<string, unknown>
}

type Errors = Partial<Record<'origin' | 'destination' | 'departure' | 'load', string>>

function serverMessage(details: Record<string, unknown> | undefined, key: string): string | undefined {
  const v = details?.[key]
  if (Array.isArray(v)) return String(v[0])
  if (v && typeof v === 'object') return Object.values(v as Record<string, unknown>).flat().map(String)[0]
  return undefined
}

export function TripForm({ onSubmit, isPending, serverErrors }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null)
  const [destination, setDestination] = useState<Place | null>(null)
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextWholeHour()))
  const [load, setLoad] = useState('36000')
  const [interval, setSampleInterval] = useState<SampleInterval>(25)
  const [windMetric, setWindMetric] = useState<WindMetric>('gust')
  const [errors, setErrors] = useState<Errors>({})

  const validate = (): Errors => {
    const e: Errors = {}
    if (!origin) e.origin = 'Pick an origin from the list.'
    if (!destination) e.destination = 'Pick a destination from the list.'
    if (origin && destination && origin.lat === destination.lat && origin.lon === destination.lon)
      e.destination = 'Destination must differ from the origin.'
    const when = new Date(departure)
    const now = Date.now()
    if (Number.isNaN(when.getTime())) e.departure = 'Enter a departure date and time.'
    else if (when.getTime() < now - 3_600_000) e.departure = "Departure can't be in the past."
    else if (when.getTime() > now + 7 * 86_400_000) e.departure = 'Departure must be within 7 days.'
    const lb = Number(load)
    if (!load || Number.isNaN(lb) || lb < 0) e.load = 'Enter the load weight in pounds.'
    else if (lb > MAX_LOAD_LB) e.load = `Load can't exceed ${MAX_LOAD_LB.toLocaleString()} lb.`
    return e
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const found = validate()
    setErrors(found)
    if (Object.keys(found).length || !origin || !destination) return
    onSubmit({
      origin,
      destination,
      departure_time: new Date(departure).toISOString(),
      load_weight_lb: Number(load),
      sample_interval_mi: interval,
      wind_metric: windMetric,
    })
  }

  const applyPreset = (p: Preset) => {
    setOrigin(p.origin)
    setDestination(p.destination)
    setLoad(String(p.load))
    setErrors({})
  }

  const err = (key: keyof Errors, server: string) => errors[key] ?? serverMessage(serverErrors, server)

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <div>
        <p className="mb-1.5 text-xs font-medium text-slate-500">Try a demo trip</p>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p.name}
              type="button"
              onClick={() => applyPreset(p)}
              className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700 transition hover:border-sky-300 hover:bg-sky-50"
            >
              {p.name}
            </button>
          ))}
        </div>
      </div>

      <PlaceAutocomplete
        label="Origin"
        placeholder="City or address"
        value={origin}
        onChange={setOrigin}
        error={err('origin', 'origin')}
      />
      <PlaceAutocomplete
        label="Destination"
        placeholder="City or address"
        value={destination}
        onChange={setDestination}
        error={err('destination', 'destination')}
      />

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="departure" className="mb-1 block text-xs font-medium text-slate-600">
            Departure ({localTimezoneName()})
          </label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            onChange={(e) => setDeparture(e.target.value)}
            aria-invalid={!!err('departure', 'departure_time')}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-sm shadow-sm outline-none focus:ring-2 focus:ring-sky-500"
          />
          {err('departure', 'departure_time') && (
            <p className="mt-1 text-xs text-red-600">{err('departure', 'departure_time')}</p>
          )}
        </div>
        <div>
          <label htmlFor="load" className="mb-1 block text-xs font-medium text-slate-600">
            Load weight (lb)
          </label>
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_LOAD_LB}
            step={500}
            value={load}
            onChange={(e) => setLoad(e.target.value)}
            aria-invalid={!!err('load', 'load_weight_lb')}
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:ring-2 focus:ring-sky-500"
          />
          {err('load', 'load_weight_lb') && <p className="mt-1 text-xs text-red-600">{err('load', 'load_weight_lb')}</p>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <fieldset>
          <legend className="mb-1 text-xs font-medium text-slate-600">Weather checkpoint every</legend>
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5 shadow-sm">
            {INTERVALS.map((mi) => (
              <button
                key={mi}
                type="button"
                aria-pressed={interval === mi}
                onClick={() => setSampleInterval(mi)}
                className={`flex-1 rounded px-2 py-1.5 text-sm transition ${
                  interval === mi ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {mi} mi
              </button>
            ))}
          </div>
        </fieldset>
        <div>
          <label htmlFor="wind-metric" className="mb-1 block text-xs font-medium text-slate-600">
            Wind rule uses
          </label>
          <select
            id="wind-metric"
            value={windMetric}
            onChange={(e) => setWindMetric(e.target.value as WindMetric)}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-2 text-sm shadow-sm outline-none focus:ring-2 focus:ring-sky-500"
          >
            <option value="gust">Gusts (safer)</option>
            <option value="sustained">Sustained wind</option>
          </select>
        </div>
      </div>

      <button
        type="submit"
        disabled={isPending}
        className="w-full rounded-md bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-sky-700 disabled:cursor-wait disabled:opacity-70"
      >
        {isPending ? 'Planning routes…' : 'Find the safest route'}
      </button>
    </form>
  )
}
