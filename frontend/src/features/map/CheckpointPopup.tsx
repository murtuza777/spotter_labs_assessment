import { Popup } from 'react-map-gl/maplibre'
import type { Checkpoint, PlannedRoute, WindMetric } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { riskColor, riskLabel } from '../../lib/risk'

interface Props {
  route: PlannedRoute
  checkpoint: Checkpoint
  loadLb: number
  windMetric: WindMetric
  onClose: () => void
}

export function CheckpointPopup({ route, checkpoint: cp, loadLb, windMetric, onClose }: Props) {
  const w = cp.weather
  const level = cp.risk?.level
  return (
    <Popup
      longitude={cp.lon}
      latitude={cp.lat}
      anchor="bottom"
      offset={12}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      maxWidth="280px"
    >
      <div className="space-y-1.5 text-xs text-slate-700">
        <div className="flex items-center justify-between gap-3">
          <span className="font-semibold text-slate-900">
            Route {route.id} · mile {Math.round(cp.mile)}
          </span>
          <span
            className="rounded px-1.5 py-0.5 text-[11px] font-bold text-white"
            style={{ backgroundColor: riskColor(level) }}
          >
            {level ? riskLabel(level) : 'No forecast'}
          </span>
        </div>
        <p>
          <span className="text-slate-500">ETA</span> {formatDateTime(cp.eta)}
        </p>
        {w ? (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            <dt className="text-slate-500">Gusts{windMetric === 'gust' && ' (rule)'}</dt>
            <dd className="text-right tabular-nums">{w.gust_mph.toFixed(0)} mph</dd>
            <dt className="text-slate-500">Sustained{windMetric === 'sustained' && ' (rule)'}</dt>
            <dd className="text-right tabular-nums">{w.wind_mph.toFixed(0)} mph</dd>
            <dt className="text-slate-500">Rain</dt>
            <dd className="text-right tabular-nums">{w.rain_in_hr.toFixed(2)} in/hr</dd>
            <dt className="text-slate-500">Snow</dt>
            <dd className="text-right tabular-nums">{w.snow_in_hr.toFixed(2)} in/hr</dd>
          </dl>
        ) : (
          <p className="text-slate-500">
            No forecast for this place and hour, so this stretch is unscored (not assumed safe).
          </p>
        )}
        {cp.risk && cp.risk.reasons.length > 0 && (
          <ul className="list-disc space-y-0.5 border-t border-slate-100 pl-4 pt-1.5">
            {cp.risk.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-slate-400">
          Forecast at the truck's ETA (hour ending {formatDateTime(cp.forecast_hour)}) · load{' '}
          {loadLb.toLocaleString()} lb
        </p>
      </div>
    </Popup>
  )
}
