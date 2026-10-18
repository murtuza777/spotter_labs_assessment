import { useEffect } from 'react'
import type { HeatmapMetric, PlannedRoute } from '../../api/types'
import { RiskBadge } from '../../components/RiskBadge'
import { Disclosure } from '../../components/Disclosure'
import { Segmented } from '../../components/Segmented'
import { Spinner } from '../../components/icons'
import { formatClock, formatDateTime, formatRiskMiles } from '../../lib/format'
import { METRICS } from '../../lib/heatmap'
import { METRIC_LABEL } from '../../lib/risk'
import { truckStatus } from '../../lib/routeModel'
import { MAX_HOUR, useTripStore } from '../../store/tripStore'
import { ForecastLegend } from './ForecastLegend'

const PLAY_SPEED_H_PER_S = 4
const TICKS = [0, 12, 24, 36, 48]
// Credit lines the weather providers' terms ask for, shown only for providers actually used.
const WEATHER_CREDITS: Record<string, { text: string; href: string }> = {
  'open-meteo': { text: 'Weather data by Open-Meteo.com (CC BY 4.0)', href: 'https://open-meteo.com/' },
  weatherapi: { text: 'Powered by WeatherAPI.com', href: 'https://www.weatherapi.com/' },
  nws: { text: 'Forecasts from NOAA/National Weather Service', href: 'https://www.weather.gov/' },
}

interface Props {
  departure: string
  route: PlannedRoute | null
  /** How the backend classed the selected route, e.g. "Recommended" or "Not eligible: No Travel". */
  routeStatus?: string
  heatmapState: 'loading' | 'ready' | 'error'
  onRetry: () => void
  /** Spacing of the heatmap's forecast grid, in degrees. */
  gridStepDeg?: number
  /** Providers behind the forecasts on screen, from the API's meta.weather_sources. */
  weatherSources?: string[]
}

/** Drives the store's `hour` with requestAnimationFrame while playing. */
function usePlayback() {
  const isPlaying = useTripStore((s) => s.isPlaying)
  useEffect(() => {
    if (!isPlaying) return
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      const { hour, setHour, setPlaying } = useTripStore.getState()
      const next = hour + ((now - last) / 1000) * PLAY_SPEED_H_PER_S
      last = now
      if (next >= MAX_HOUR) {
        setHour(MAX_HOUR)
        setPlaying(false)
        return
      }
      setHour(next)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [isPlaying])
}

/** The forecast timeline under the map: time, 0-48 h slider, variable, color key, credits. */
export function ForecastDock({
  departure,
  route,
  routeStatus,
  heatmapState,
  onRetry,
  gridStepDeg,
  weatherSources = [],
}: Props) {
  usePlayback()
  const hour = useTripStore((s) => s.hour)
  const isPlaying = useTripStore((s) => s.isPlaying)
  const metric = useTripStore((s) => s.heatmapMetric)
  const visible = useTripStore((s) => s.heatmapVisible)
  const { setHour, setPlaying, setHeatmapMetric, toggleHeatmap } = useTripStore.getState()

  const at = new Date(Date.parse(departure) + hour * 3_600_000)
  const arrivalHours = route ? route.duration_s / 3600 : null
  const arrivalPct = arrivalHours !== null && arrivalHours <= MAX_HOUR ? (arrivalHours / MAX_HOUR) * 100 : null
  const truck = route ? truckStatus(route, departure, hour) : null
  const credits = weatherSources.filter((s) => s in WEATHER_CREDITS)

  return (
    <section aria-label="Forecast timeline" className="@container border-t border-slate-200 bg-white px-3 pt-2.5 pb-3 sm:px-4">
      <div className="flex flex-col gap-1 @xl:flex-row @xl:items-center @xl:gap-5">
        <div className="flex shrink-0 items-center gap-3 @xl:w-56">
          <button
            type="button"
            onClick={() => {
              if (!isPlaying && hour >= MAX_HOUR) setHour(0)
              setPlaying(!isPlaying)
            }}
            aria-label={isPlaying ? 'Pause forecast animation' : 'Play forecast animation'}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white transition hover:bg-slate-700 active:bg-slate-800"
          >
            {isPlaying ? (
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden="true">
                <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" className="ml-0.5 h-4 w-4 fill-current" aria-hidden="true">
                <path d="M7 4v16l13-8z" />
              </svg>
            )}
          </button>
          <div className="min-w-0 leading-tight">
            <p className="text-xs font-medium text-slate-500">Forecast time</p>
            <p className="text-[15px] font-semibold text-slate-900 tabular-nums">{formatDateTime(at)}</p>
            <p className="text-[13px] text-slate-600 tabular-nums">Departure +{hour.toFixed(hour % 1 ? 1 : 0)} h</p>
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="relative">
            <input
              type="range"
              min={0}
              max={MAX_HOUR}
              step={0.25}
              value={hour}
              onChange={(e) => {
                setPlaying(false)
                setHour(Number(e.target.value))
              }}
              aria-label="Forecast hour after departure"
              aria-valuetext={`${formatDateTime(at)}, departure plus ${Math.round(hour)} hours`}
              className="forecast-range"
              style={{ '--fill': `${(hour / MAX_HOUR) * 100}%` } as React.CSSProperties}
            />
            {arrivalPct !== null && (
              <span
                className="pointer-events-none absolute top-0 -translate-x-1/2 text-[11px] leading-none font-semibold whitespace-nowrap text-green-800"
                style={{ left: `${arrivalPct}%` }}
                aria-hidden="true"
              >
                Arrive ▾
              </span>
            )}
          </div>
          <div className="relative -mt-1 h-4 text-[11px] text-slate-500 tabular-nums" aria-hidden="true">
            {TICKS.map((h) => (
              <span
                key={h}
                className={`absolute top-0 ${h === 0 ? 'left-0' : h === MAX_HOUR ? 'right-0' : '-translate-x-1/2'}`}
                style={h === 0 || h === MAX_HOUR ? undefined : { left: `${(h / MAX_HOUR) * 100}%` }}
              >
                {h === 0 ? 'Depart' : `+${h} h`}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-5 gap-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            options={METRICS}
            value={metric}
            onChange={(m: HeatmapMetric) => setHeatmapMetric(m)}
            label={(m) => METRIC_LABEL[m]}
            ariaLabel="Heatmap variable"
            className="w-full @sm:w-auto [&>button]:min-w-16"
          />
          <label className="inline-flex h-10 cursor-pointer items-center gap-2 rounded-md px-1.5 text-sm font-medium text-slate-700 select-none hover:bg-slate-50">
            <input type="checkbox" checked={visible} onChange={toggleHeatmap} className="h-5 w-5 accent-brand-600" />
            Heatmap
          </label>
          <span className="min-h-5 text-[13px]" aria-live="polite">
            {heatmapState === 'loading' && (
              <span className="inline-flex items-center gap-1.5 text-slate-600">
                <Spinner className="h-3.5 w-3.5 text-brand-600" />
                Loading forecast grid…
              </span>
            )}
            {heatmapState === 'error' && (
              <span className="text-red-700">
                Heatmap unavailable.{' '}
                <button type="button" onClick={onRetry} className="font-semibold underline underline-offset-2">
                  Retry
                </button>
              </span>
            )}
          </span>
        </div>
        <ForecastLegend />
      </div>

      <div className="mt-2 flex flex-wrap items-start justify-between gap-x-5 gap-y-1.5 border-t border-slate-100 pt-2">
        {route && truck && (
          <p className="flex min-w-0 flex-1 basis-80 flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] text-slate-700" aria-live="off">
            <span className="font-semibold text-slate-900">Route {route.id}</span>
            {routeStatus && <span className="text-slate-500">({routeStatus})</span>}
            <span className="text-slate-400" aria-hidden="true">
              ·
            </span>
            {truck.arrived ? (
              <span>
                Route {route.id} has arrived ({formatClock(route.arrival_time)}).
              </span>
            ) : (
              <>
                <span>
                  Truck on Route {route.id}: mile {formatRiskMiles(truck.mile)} of {formatRiskMiles(route.distance_mi)}
                </span>
                <span className="text-slate-400" aria-hidden="true">
                  ·
                </span>
                <span>
                  nearest checkpoint, mi {Math.round(truck.nearest.mile)} (ETA {formatClock(truck.nearest.eta)})
                </span>
                <RiskBadge level={truck.nearest.risk?.level} />
              </>
            )}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          <Disclosure summary="How to read the map">
            <p className="mt-1 max-w-md leading-relaxed text-slate-600">
              The route line and checkpoint dots show each checkpoint's forecast for the hour the truck gets there. The
              heatmap shows the selected forecast time across the trip corridor, smoothed between point forecasts on a
              {gridStepDeg ? ` ${gridStepDeg}°` : ''} grid: an interpolation, not radar. Grey dots are grid cells with no
              forecast for that hour; a dashed grey route line or a hollow checkpoint has no forecast and is not scored.
            </p>
          </Disclosure>
          {credits.map((s) => (
            <a
              key={s}
              href={WEATHER_CREDITS[s].href}
              target="_blank"
              rel="noreferrer"
              className="underline-offset-2 hover:text-slate-700 hover:underline"
            >
              {WEATHER_CREDITS[s].text}
            </a>
          ))}
        </div>
      </div>
    </section>
  )
}
