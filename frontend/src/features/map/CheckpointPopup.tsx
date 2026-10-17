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
        {w && cp.risk ? (
          <>
            <table className="w-full border-collapse text-[11px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-slate-400">
                  <th className="pb-0.5 font-medium">Factor</th>
                  <th className="pb-0.5 text-right font-medium">Forecast</th>
                  <th className="pb-0.5 pl-2 text-right font-medium">Level</th>
                </tr>
              </thead>
              <tbody>
                {cp.risk.factors.map((f) => (
                  <tr key={f.name} className="border-t border-slate-100">
                    <td className="py-0.5 capitalize">{f.label}</td>
                    <td className="py-0.5 text-right tabular-nums">
                      {f.unit === 'mph' ? f.value.toFixed(0) : f.value.toFixed(2)} {f.unit}
                    </td>
                    <td className="py-0.5 pl-2 text-right font-semibold" style={{ color: riskColor(f.level) }}>
                      {f.level !== f.base_level && (
                        <span className="font-normal text-slate-400">{riskLabel(f.base_level)} → </span>
                      )}
                      {riskLabel(f.level)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {cp.risk.factors
              .filter((f) => f.load_rule)
              .map((f) => (
                <p key={f.name} className="rounded bg-purple-50 px-1.5 py-1 text-[11px] text-purple-900">
                  Load rule: {f.load_rule}
                </p>
              ))}
            <p className="text-[11px] text-slate-600">
              Checkpoint risk is the worst factor: <b style={{ color: riskColor(level) }}>{riskLabel(level)}</b>.{' '}
              {windMetric === 'gust'
                ? `Wind uses gusts (sustained wind was ${w.wind_mph.toFixed(0)} mph).`
                : `Wind uses sustained speed (gusts were ${w.gust_mph.toFixed(0)} mph).`}
            </p>
          </>
        ) : (
          <p className="text-slate-500">
            No forecast for this place and hour, so this stretch is unscored (not assumed safe).
          </p>
        )}
        <p className="text-[10px] text-slate-400">
          Forecast at the truck's ETA: the hour ending {formatDateTime(cp.forecast_hour)} ({cp.forecast_hour.slice(11, 16)} UTC), grid cell{' '}
          {cp.weather_cell ? `${cp.weather_cell.lat.toFixed(2)}, ${cp.weather_cell.lon.toFixed(2)}` : 'n/a'} · load{' '}
          {loadLb.toLocaleString()} lb
        </p>
      </div>
    </Popup>
  )
}
