import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, type Page } from '@playwright/test'

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), 'fixtures')

export type Scenario = 'mixed' | 'no_safe_route' | 'partial_forecast' | 'detour' | 'two_routes' | 'weather_outage'

/** Fixtures exported from the real backend pipeline (backend/scripts/export_e2e_fixtures.py). */
export function fixture<T = any>(name: string): T {
  return JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), 'utf8')) as T
}

const PLACES = [
  { label: 'Denver, Colorado, US', lat: 39.7392, lon: -104.9903 },
  { label: 'Salt Lake City, Utah, US', lat: 40.7608, lon: -111.891 },
]

// A minimal basemap so the map loads without the network (no tiles, no glyphs needed).
const MIN_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eef2f7' } }],
}

interface MockOptions {
  scenario?: Scenario
  /** 'live' loads the real basemap (screenshots); the default mocks it for offline runs. */
  basemap?: 'mock' | 'live'
  planDelayMs?: number
  planStatus?: number
  planBody?: unknown
}

export interface Calls {
  plan: number
  heatmap: number
  geocode: number
  health: number
}

export async function mockApi(page: Page, opts: MockOptions = {}): Promise<Calls> {
  const { scenario = 'mixed', planDelayMs = 700, planStatus = 200, planBody, basemap = 'mock' } = opts
  const calls: Calls = { plan: 0, heatmap: 0, geocode: 0, health: 0 }

  if (basemap === 'mock')
    await page.route('https://tiles.openfreemap.org/**', (route) =>
      route.request().url().includes('/styles/') ? route.fulfill({ json: MIN_STYLE }) : route.abort(),
    )
  await page.route('**/api/health/', (route) => {
    calls.health++
    return route.fulfill({ json: { status: 'ok' } })
  })
  await page.route('**/api/geocode/**', (route) => {
    calls.geocode++
    const q = (new URL(route.request().url()).searchParams.get('q') ?? '').toLowerCase()
    return route.fulfill({ json: { results: PLACES.filter((p) => p.label.toLowerCase().includes(q)) } })
  })
  await page.route('**/api/plan/', async (route) => {
    calls.plan++
    await new Promise((r) => setTimeout(r, planDelayMs))
    return route.fulfill({ status: planStatus, json: planBody ?? fixture(`plan_${scenario}`) })
  })
  await page.route('**/api/heatmap/', (route) => {
    calls.heatmap++
    return route.fulfill({ json: fixture(`heatmap_${scenario}`) })
  })
  return calls
}

export async function pickPlace(page: Page, label: 'Origin' | 'Destination', typed: string, choice: string) {
  const input = page.getByRole('combobox', { name: label })
  await input.fill(typed)
  await page.getByRole('option', { name: choice }).click()
  await expect(input).toHaveValue(choice)
}

/** Fill the form the way a user would and submit. */
export async function planTrip(page: Page, { load = '36000' }: { load?: string } = {}) {
  await pickPlace(page, 'Origin', 'Denv', 'Denver, Colorado, US')
  await pickPlace(page, 'Destination', 'Salt', 'Salt Lake City, Utah, US')
  await page.getByLabel('Load weight (lb)').fill(load)
  await page.getByRole('button', { name: 'Find the safest route' }).click()
}

/** Wait until the map has the plan's layers (dev builds expose the map as window.__map). */
export async function waitForMapLayers(page: Page, withHeatmap = true) {
  await page.waitForFunction(
    (heat) => {
      const map = (window as any).__map
      return !!map && !!map.getLayer('checkpoints') && (!heat || !!map.getLayer('weather-heatmap-48'))
    },
    withHeatmap,
    { timeout: 15_000 },
  )
}

export function routeCards(page: Page) {
  return page.getByRole('region', { name: 'Route options' }).locator('button[aria-pressed]', { hasText: 'Route ' })
}
