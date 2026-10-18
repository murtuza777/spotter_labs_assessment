import type { PlanRequest } from '../../api/types'
import { EditIcon } from '../../components/icons'
import { formatDateTime, formatWeight } from '../../lib/format'

/** The trip being evaluated, shown in place of the form once a plan is on screen. */
export function TripSummary({ request, onEdit }: { request: PlanRequest; onEdit: () => void }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="min-w-0">
        <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Trip</p>
        <p className="mt-0.5 font-semibold break-words text-slate-900">
          {request.origin.label}{' '}
          <span className="text-slate-400" aria-hidden="true">
            →
          </span>
          <span className="sr-only">to</span> {request.destination.label}
        </p>
        <p className="mt-1 text-sm text-slate-600">
          Departs {formatDateTime(request.departure_time)} · {formatWeight(request.load_weight_lb)} · checkpoints
          every {request.sample_interval_mi} mi · {request.wind_metric === 'gust' ? 'gust' : 'sustained wind'} rule
        </p>
      </div>
      <button
        type="button"
        onClick={onEdit}
        className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-100 active:bg-slate-200"
      >
        <EditIcon />
        Edit trip
      </button>
    </div>
  )
}
