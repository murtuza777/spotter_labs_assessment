import { useEffect, useState } from 'react'

const STEPS = [
  { after: 0, text: 'Requesting 3 truck routes…' },
  { after: 3, text: 'Placing checkpoints and estimating arrival times…' },
  { after: 5, text: 'Fetching the forecast at each checkpoint’s arrival hour…' },
  { after: 15, text: 'The free weather service is busy; still working (first plans can take ~30 s)…' },
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
    <div className="rounded-lg border border-sky-200 bg-sky-50 p-3" role="status" aria-live="polite">
      <div className="mb-2 h-1 overflow-hidden rounded-full bg-sky-100">
        <div className="h-full w-1/3 animate-[progress_1.2s_ease-in-out_infinite] rounded-full bg-sky-500" />
      </div>
      <p className="text-sm text-sky-900">{step.text}</p>
      <p className="mt-0.5 text-[11px] tabular-nums text-sky-700">{Math.floor(elapsed)} s</p>
    </div>
  )
}
