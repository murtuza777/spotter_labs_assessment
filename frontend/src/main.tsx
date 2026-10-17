import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { fetchHealth } from './api/client'
import App from './App.tsx'
import './index.css'

// Wake the API early: a free-tier backend may be asleep, and this starts it while the user
// is still filling in the form.
fetchHealth().catch(() => {})

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
