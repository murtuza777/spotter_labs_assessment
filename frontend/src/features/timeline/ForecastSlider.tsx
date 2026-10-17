import { useEffect } from 'react'
import type { HeatmapMetric } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { METRICS } from '../../lib/heatmap'
import { METRIC_LABEL } from '../../lib/risk'
import { MAX_HOUR, useTripStore } from '../../store/tripStore'

const PLAY_SPEED_H_PER_S = 4

interface Props {
  departure: string
  arrivalHours: number | null
  heatmapState: 'loading' | 'ready' | 'error'
  onRetry: () => void
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

export function ForecastSlider({ departure, arrivalHours, heatmapState, onRetry }: Props) {
  usePlayback()
  const hour = useTripStore((s) => s.hour)
  const isPlaying = useTripStore((s) => s.isPlaying)
  const metric = useTripStore((s) => s.heatmapMetric)
  const visible = useTripStore((s) => s.heatmapVisible)
  const { setHour, setPlaying, setHeatmapMetric, toggleHeatmap } = useTripStore.getState()

  const at = new Date(Date.parse(departure) + hour * 3_600_000)
  const arrivalPct = arrivalHours !== null && arrivalHours <= MAX_HOUR ? (arrivalHours / MAX_HOUR) * 100 : null

  return (
    <div className="pointer-events-auto rounded-xl border border-slate-200 bg-white/95 p-2.5 shadow-lg backdrop-blur sm:p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              if (!isPlaying && hour >= MAX_HOUR) setHour(0)
              setPlaying(!isPlaying)
            }}
            aria-label={isPlaying ? 'Pause forecast animation' : 'Play forecast animation'}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900 text-white transition hover:bg-slate-700"
          >
            {isPlaying ? (
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden="true">
                <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden="true">
                <path d="M7 4v16l13-8z" />
              </svg>
            )}
          </button>
          <div className="leading-tight">
            <p className="text-sm font-semibold tabular-nums text-slate-900">{formatDateTime(at)}</p>
            <p className="text-[11px] tabular-nums text-slate-500">Departure +{hour.toFixed(hour % 1 ? 1 : 0)} h</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {heatmapState === 'loading' && <span className="text-[11px] text-slate-500">Loading forecast grid…</span>}
          {heatmapState === 'error' && (
            <button type="button" onClick={onRetry} className="text-[11px] font-medium text-red-600 underline">
              Heatmap failed, retry
            </button>
          )}
          <div className="flex rounded-md border border-slate-200 p-0.5" role="group" aria-label="Heatmap metric">
            {METRICS.map((m: HeatmapMetric) => (
              <button
                key={m}
                type="button"
                aria-pressed={metric === m}
                onClick={() => setHeatmapMetric(m)}
                className={`rounded px-1.5 py-1 text-xs transition sm:px-2 ${
                  metric === m ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {METRIC_LABEL[m]}
              </button>
            ))}
          </div>
          <label className="flex cursor-pointer items-center gap-1 text-xs text-slate-600">
            <input type="checkbox" checked={visible} onChange={toggleHeatmap} className="accent-slate-900" />
            Heatmap
          </label>
        </div>
      </div>

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
          className="w-full accent-sky-600"
        />
        {arrivalPct !== null && (
          <span
            className="pointer-events-none absolute -bottom-3 -translate-x-1/2 text-[10px] font-medium text-emerald-700"
            style={{ left: `${arrivalPct}%` }}
          >
            ▲ arrive
          </span>
        )}
        <div className="mt-0.5 flex justify-between text-[10px] text-slate-400">
          <span>Depart</span>
          <span>+12 h</span>
          <span>+24 h</span>
          <span>+36 h</span>
          <span>+48 h</span>
        </div>
      </div>
    </div>
  )
}
