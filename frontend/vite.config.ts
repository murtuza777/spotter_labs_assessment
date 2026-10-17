/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // MapLibre 6 ships prebuilt ESM whose main-thread code must match its worker. Vite's dep
  // pre-bundling rewrites it and the workers then fail on every tile, so serve it untouched.
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
  server: {
    // Same-origin /api in dev, mirroring the Vercel rewrite in production.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
