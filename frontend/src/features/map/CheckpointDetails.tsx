import type { Checkpoint, PlannedRoute, WindMetric } from '../../api/types'
import { Disclosure } from '../../components/Disclosure'
import { RiskBadge } from '../../components/RiskBadge'
import { CloseIcon } from '../../components/icons'
import { formatDateTime } from '../../lib/format'
import { riskColor, riskLabel } from '../../lib/risk'
import { describeWeatherSource } from '../../lib/weatherSource'

export interface CheckpointDetailsProps {
  route: PlannedRoute
  checkpoint: Checkpoint
  loadLb: number
  windMetric: WindMetric
  onClose: () => void
}

/** Everything about one checkpoint: reading per factor, the rule applied, and provenance. */
export function CheckpointDetails({ route, checkpoint: cp, loadLb, windMetric, onClose }: CheckpointDetailsProps) {
  const w = cp.weather
  const level = cp.risk?.level
  const source = describeWeatherSource(cp.weather_source)
  const providers = new Set(Object.values(cp.weather_source ?? {}).filter(Boolean))

  return (
    <div className="space-y-2 text-sm text-slate-700">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 pt-1">
          <p className="font-semibold text-slate-900">
            Route {route.id} · mile {Math.round(cp.mile)}
          </p>
          <p className="text-[13px] text-slate-600">
            <span className="text-slate-500">ETA</span> {formatDateTime(cp.eta)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <RiskBadge level={level} size="md" />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close checkpoint details"
            className="-mr-2 flex h-11 w-11 items-center justify-center rounded-md text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
          >
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>
      </div>

      {w && cp.risk ? (
        <>
          <table className="w-full border-collapse text-[13px]">
            <caption className="sr-only">Forecast and risk level for each factor</caption>
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th scope="col" className="pb-1 font-medium">
                  Factor
                </th>
                <th scope="col" className="pb-1 text-right font-medium">
                  Forecast
                </th>
                <th scope="col" className="pb-1 pl-3 text-right font-medium">
                  Level
                </th>
              </tr>
            </thead>
            <tbody>
              {cp.risk.factors.map((f) => (
                <tr key={f.name} className="border-t border-slate-100">
                  <td className="py-1 capitalize">{f.label}</td>
                  <td className="py-1 text-right tabular-nums">
                    {f.unit === 'mph' ? f.value.toFixed(0) : f.value.toFixed(2)} {f.unit}
                  </td>
                  <td className="py-1 pl-3 text-right font-semibold whitespace-nowrap text-slate-900">
                    {f.level !== f.base_level && <span className="font-normal text-slate-500">{riskLabel(f.base_level)} → </span>}
                    <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: riskColor(f.level) }} aria-hidden="true" />
                    {riskLabel(f.level)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {cp.risk.factors
            .filter((f) => f.load_rule)
            .map((f) => (
              <p key={f.name} className="rounded-md bg-purple-50 px-2 py-1.5 text-[13px] text-purple-900">
                Load rule: {f.load_rule}
              </p>
            ))}
          <p className="text-[13px] text-slate-600">
            Checkpoint risk is the worst factor: <b className="text-slate-900">{riskLabel(level)}</b>.{' '}
            {windMetric === 'gust'
              ? `Wind uses gusts (sustained wind was ${w.wind_mph.toFixed(0)} mph).`
              : `Wind uses sustained speed (gusts were ${w.gust_mph.toFixed(0)} mph).`}
          </p>
        </>
      ) : (
        <p className="rounded-md border border-dashed border-slate-300 px-2 py-1.5 text-[13px] text-slate-700">
          No forecast for this place and hour, so this stretch is unscored (not assumed safe).
        </p>
      )}

      {source && (
        <p className="text-[13px] text-slate-600">
          <span className="text-slate-500">Weather source:</span> {source}
          {providers.size > 1 && (
            <span className="block text-xs text-slate-500">
              Combined reading: the fallback provider supplied the values the primary provider didn't have for this
              hour.
            </span>
          )}
        </p>
      )}

      <Disclosure summary="Forecast details" className="text-xs text-slate-500">
        <p className="mt-0.5 leading-relaxed">
          Forecast for the truck's ETA: the hour ending {formatDateTime(cp.forecast_hour)} ({cp.forecast_hour.slice(11, 16)}{' '}
          UTC), grid cell{' '}
          {cp.weather_cell ? `${cp.weather_cell.lat.toFixed(2)}, ${cp.weather_cell.lon.toFixed(2)}` : 'n/a'} · load{' '}
          {loadLb.toLocaleString()} lb
        </p>
      </Disclosure>
    </div>
  )
}
