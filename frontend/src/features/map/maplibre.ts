import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

// MapLibre 6 resolves its worker relative to its own module URL, which breaks once Vite
// pre-bundles (dev) or chunks (build) the library. Point it at the emitted worker asset.
setWorkerUrl(workerUrl)
