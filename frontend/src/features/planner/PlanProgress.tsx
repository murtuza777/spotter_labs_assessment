import { useEffect, useState } from 'react'

const STEPS = [
  { after: 0, text: 'Requesting 3 truck routes…' },
  { after: 3, text: 'Placing checkpoints and estimating arrival times…' },
  { after: 5, text: 'Fetching the forecast at each checkpoint’s arrival hour…' },
  { after: 15, text: 'Still fetching forecasts. A first plan for a new area can take up to 30 s.' },
]

export function PlanProgress() {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const id = setInterval(() => setElapsed((Date.now() - start) / 1000), 500)
    return () => clearInterval(id)
  }, [])
  const step = [...STEPS].reverse().find((s) => elapsed >= s.after) ?? STEPS[0]
  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50 p-4" role="status" aria-live="polite">
      <div className="mb-3 h-1 overflow-hidden rounded-full bg-brand-100">
        <div className="h-full w-1/3 animate-[progress_1.2s_ease-in-out_infinite] rounded-full bg-brand-600" />
      </div>
      <p className="text-sm font-medium text-brand-900">{step.text}</p>
      <p className="mt-1 text-xs text-brand-800 tabular-nums">{Math.floor(elapsed)} s</p>
    </div>
  )
}
