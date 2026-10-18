import { useState } from 'react'
import type { Place, PlanRequest, SampleInterval, WindMetric } from '../../api/types'
import { Field, INPUT_CLASS } from '../../components/Field'
import { Spinner } from '../../components/icons'
import { Segmented } from '../../components/Segmented'
import { localTimezoneName, nextWholeHour, toLocalInputValue } from '../../lib/format'
import { PlaceAutocomplete } from './PlaceAutocomplete'
import { PRESETS, type Preset } from './presets'

const INTERVALS: readonly SampleInterval[] = [10, 25, 50]
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
    if (isPending) return // Enter key while a plan is running: no second request
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
  const departureError = err('departure', 'departure_time')
  const loadError = err('load', 'load_weight_lb')

  return (
    <form onSubmit={submit} className="@container space-y-4" noValidate>
      <div>
        <p id="demo-trips" className="mb-2 text-sm font-medium text-slate-700">
          Try a demo trip
        </p>
        <div className="flex flex-wrap gap-2" role="group" aria-labelledby="demo-trips">
          {PRESETS.map((p) => (
            <button
              key={p.name}
              type="button"
              onClick={() => applyPreset(p)}
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700 transition hover:border-brand-300 hover:bg-brand-50 hover:text-brand-800 active:bg-brand-100"
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

      <div className="grid gap-4 @sm:grid-cols-2 @sm:gap-3">
        <Field label={`Departure (${localTimezoneName()})`} htmlFor="departure" error={departureError}>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            onChange={(e) => setDeparture(e.target.value)}
            aria-invalid={!!departureError}
            aria-describedby={departureError ? 'departure-error' : undefined}
            className={INPUT_CLASS}
          />
        </Field>
        <Field label="Load weight (lb)" htmlFor="load" error={loadError}>
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_LOAD_LB}
            step={500}
            value={load}
            onChange={(e) => setLoad(e.target.value)}
            aria-invalid={!!loadError}
            aria-describedby={loadError ? 'load-error' : undefined}
            className={INPUT_CLASS}
          />
        </Field>
      </div>

      <div className="grid gap-4 @sm:grid-cols-2 @sm:gap-3">
        <div className="min-w-0">
          <p id="interval-label" className="mb-1.5 text-sm font-medium text-slate-700">
            Weather checkpoint every
          </p>
          <Segmented
            options={INTERVALS}
            value={interval}
            onChange={setSampleInterval}
            label={(mi) => `${mi} mi`}
            ariaLabelledBy="interval-label"
          />
        </div>
        <Field label="Wind rule uses" htmlFor="wind-metric">
          <select
            id="wind-metric"
            value={windMetric}
            onChange={(e) => setWindMetric(e.target.value as WindMetric)}
            className={`${INPUT_CLASS} pr-8`}
          >
            <option value="gust">Gusts (safer)</option>
            <option value="sustained">Sustained wind</option>
          </select>
        </Field>
      </div>

      <button
        type="submit"
        disabled={isPending}
        className="flex h-12 w-full items-center justify-center gap-2 rounded-md bg-brand-600 px-4 text-[15px] font-semibold text-white shadow-sm transition hover:bg-brand-700 active:bg-brand-800 disabled:cursor-not-allowed disabled:bg-brand-600/70"
      >
        {isPending && <Spinner />}
        {isPending ? 'Planning routes…' : 'Find the safest route'}
      </button>
    </form>
  )
}
