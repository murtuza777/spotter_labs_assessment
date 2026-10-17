import { useQuery } from '@tanstack/react-query'
import { fetchHealth } from './api/client'
import { TripMap } from './features/map/TripMap'

function App() {
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth })

  return (
    <div className="flex h-full">
      <aside className="w-96 shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-4">
        <h1 className="text-lg font-semibold">Weather-Aware Truck Routing</h1>
        <p className="mt-1 text-sm text-slate-500">
          API: {health.isPending ? 'checking…' : health.isError ? 'unreachable' : health.data.status}
        </p>
      </aside>
      <main className="relative flex-1">
        <TripMap />
      </main>
    </div>
  )
}

export default App
