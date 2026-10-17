import { expect, test } from '@playwright/test'
import { decodePolyline } from '../src/lib/geo'
import { fixture, mockApi, planTrip, routeCards, waitForMapLayers } from './helpers'

interface Plan {
  recommended_route_id: string
  recommendation: { reason: string; warnings: string[] }
  routes: {
    id: string
    rank: number
    geometry: string
    checkpoints: { mile: number }[]
    summary: { miles_by_level: Record<string, number> }
  }[]
}

const mixed = fixture<Plan>('plan_mixed')

test('plans a trip end to end and shows the backend ranking', async ({ page }) => {
  const calls = await mockApi(page)
  await page.goto('/')
  await expect.poll(() => calls.health).toBe(1) // wakes the API on load

  await planTrip(page)
  await expect(page.getByRole('status').filter({ hasText: 'Requesting 3 truck routes' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Planning routes…' })).toBeDisabled()

  const cards = routeCards(page)
  await expect(cards).toHaveCount(3)
  // Cards are listed best first, matching the backend's ranks.
  const ids = [...mixed.routes].sort((a, b) => a.rank - b.rank).map((r) => r.id)
  for (const [i, id] of ids.entries()) await expect(cards.nth(i)).toContainText(`Route ${id}`)

  await expect(page.getByText(`Recommended: Route ${mixed.recommended_route_id}`)).toBeVisible()
  await expect(page.getByText(mixed.recommendation.reason)).toBeVisible()
  await expect(cards.first()).toContainText('★ Recommended')

  // Route A crosses the Wyoming gale: its No Travel miles are flagged, not hidden.
  const routeA = cards.filter({ hasText: 'Route A' })
  await expect(routeA).toContainText(`No Travel conditions on ${Math.round(mixed.routes[0].summary.miles_by_level.no_travel)} mi`)

  // Selecting each route shows its own checkpoints.
  for (const route of mixed.routes) {
    const card = cards.filter({ hasText: `Route ${route.id}` })
    await card.click()
    await expect(card).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByText(`Route ${route.id} checkpoints (${route.checkpoints.length})`)).toBeVisible()
  }

  await waitForMapLayers(page)
  const layers = await page.evaluate(() => (window as any).__map.getStyle().layers.map((l: { id: string }) => l.id))
  expect(layers).toEqual(expect.arrayContaining(['route-inactive', 'route-selected-risk', 'checkpoints']))
  expect(layers.filter((id: string) => id.startsWith('weather-heatmap-'))).toHaveLength(49)

  expect(calls.plan).toBe(1)
  expect(calls.heatmap).toBe(1)
})

test('fits the map to every route', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await planTrip(page)
  await waitForMapLayers(page)
  await page.waitForFunction(() => !(window as any).__map.isMoving(), null, { timeout: 10_000 })
  const coords = mixed.routes.flatMap((r) => decodePolyline(r.geometry))
  const outside = await page.evaluate((points) => {
    const bounds = (window as any).__map.getBounds()
    return points.filter((c) => !bounds.contains(c)).length
  }, coords)
  expect(coords.length).toBeGreaterThan(100)
  expect(outside).toBe(0)
})

test('forecast slider covers 0 to 48 h and only cross-fades heatmap frames', async ({ page }) => {
  const calls = await mockApi(page)
  await page.goto('/')
  await planTrip(page)
  await waitForMapLayers(page)
  const slider = page.getByRole('slider', { name: 'Forecast hour after departure' })
  const opacities = () =>
    page.evaluate(() => {
      const map = (window as any).__map
      const out: Record<number, number> = {}
      for (let h = 0; h <= 48; h++) {
        const o = map.getPaintProperty(`weather-heatmap-${h}`, 'heatmap-opacity')
        if (o > 0) out[h] = Math.round(o * 1000) / 1000
      }
      return out
    })

  await expect(page.getByText('Departure +0 h')).toBeVisible()
  expect(await opacities()).toEqual({ 0: 0.9 })

  await slider.fill('12.5')
  await expect(page.getByText('Departure +12.5 h')).toBeVisible()
  expect(await opacities()).toEqual({ 12: 0.45, 13: 0.45 })

  await slider.fill('2')
  await expect(page.getByText(/Truck on Route B: mile \d/)).toBeVisible()

  await slider.fill('48')
  await expect(page.getByText('Departure +48 h')).toBeVisible()
  expect(await opacities()).toEqual({ 48: 0.9 })
  await expect(page.getByText(/Route B has arrived/)).toBeVisible()

  // Switching metric rebuilds the frames from the same response (no refetch).
  await page.getByRole('button', { name: 'Wind', exact: true }).click()
  const weight = await page.evaluate(() => (window as any).__map.getPaintProperty('weather-heatmap-48', 'heatmap-weight'))
  expect(weight).toEqual(['coalesce', ['get', 'g48'], 0])
  await expect(page.getByText('25–35')).toBeVisible() // legend shows wind thresholds

  await page.getByRole('checkbox', { name: 'Heatmap' }).uncheck()
  expect(await opacities()).toEqual({})

  expect(calls.plan).toBe(1)
  expect(calls.heatmap).toBe(1)
})

test('checkpoint details explain the risk classification', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await planTrip(page)
  await routeCards(page).filter({ hasText: 'Route A' }).click()
  await waitForMapLayers(page)
  // The first Route A checkpoint north of 41°N gets the 50 mph gusts with a 36,000 lb load.
  await page.getByRole('button', { name: /No Travel/ }).filter({ hasText: /^mi \d+/ }).first().click()
  const popup = page.locator('.maplibregl-popup')
  await expect(popup).toContainText('Route A · mile')
  await expect(popup).toContainText('ETA')
  // One row per factor: reading and level, with the load escalation spelled out.
  await expect(popup.getByRole('row', { name: /gusts\s+50 mph\s+Severe → No Travel/i })).toBeVisible()
  await expect(popup.getByRole('row', { name: /rain/i })).toContainText('Low')
  await expect(popup.getByRole('row', { name: /snow/i })).toContainText('Low')
  await expect(popup).toContainText('Load rule: load 36,000 lb > 30,000 lb raises Severe to No Travel')
  await expect(popup).toContainText('Checkpoint risk is the worst factor: No Travel')
  await expect(popup).toContainText('grid cell')
})

test('never presents a No Travel trip as safe', async ({ page }) => {
  await mockApi(page, { scenario: 'no_safe_route' })
  await page.goto('/')
  await planTrip(page)
  await expect(page.getByText('⚠ No safe route at this departure time')).toBeVisible()
  await expect(page.getByText('No route is recommended: every route has No Travel conditions.')).toBeVisible()
  await expect(page.getByText('★ Recommended')).toHaveCount(0)
  await expect(page.getByText('Not eligible: No Travel', { exact: true })).toHaveCount(3)
  await expect(page.getByText(/is not eligible: No Travel conditions on [\d.,]+ mi \(safety constraint\)/)).toHaveCount(3)
  await expect(page.getByText(/Every route has No Travel conditions/)).toBeVisible()
  // A route is still selected and shown, so the driver can see where the danger is.
  await expect(routeCards(page).first()).toHaveAttribute('aria-pressed', 'true')
})

test('excludes No Travel routes but ranks the rest by the assessment order', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await planTrip(page)
  const routeA = routeCards(page).filter({ hasText: 'Route A' })
  await expect(routeA).toContainText('Not eligible: No Travel')
  await expect(routeA).toContainText('#3')
  await expect(page.getByText(/Route A is not eligible: No Travel conditions on/)).toBeVisible()
  await page.getByText('How routes are ranked').click()
  await expect(page.getByText(/fewest Severe miles, then fewest\s+High miles, then lowest average risk, then shortest drive time/)).toBeVisible()
  // Every card shows the ranking metrics and forecast coverage.
  for (const label of ['Distance', 'Drive', 'ETA', 'Severe mi', 'High mi', 'Avg risk', 'Forecast']) {
    await expect(routeCards(page).first()).toContainText(label)
  }
  await expect(routeCards(page).first()).toContainText('100%')
})

test('shows missing forecasts as unscored, never as calm', async ({ page }) => {
  await mockApi(page, { scenario: 'partial_forecast' })
  const heat = fixture<{ frames: { risk: (number | null)[][] } }>('heatmap_partial_forecast')
  await page.goto('/')
  await planTrip(page)
  await expect(page.getByText(/^Provisional pick: Route [ABC]$/)).toBeVisible()
  await expect(page.getByText(/No route has a complete forecast/)).toBeVisible()
  await expect(page.getByText(/No forecast for [\d.]+ mi: those miles are unscored, not safe/).first()).toBeVisible()
  await expect(page.getByRole('button', { name: /No forecast/ }).first()).toBeVisible() // checkpoint row
  await expect(routeCards(page).first()).not.toContainText('Forecast100%')

  // Heatmap: cells without data are drawn as grey dots for the selected hour only.
  await waitForMapLayers(page)
  expect(heat.frames.risk[0].some((v) => v === null)).toBe(true)
  const dots = () =>
    page.evaluate(() => {
      const map = (window as any).__map
      const visible: number[] = []
      for (let h = 0; h <= 48; h++) if (map.getPaintProperty(`weather-unknown-${h}`, 'circle-opacity') > 0) visible.push(h)
      return { visible, filter: map.getFilter('weather-unknown-0') }
    })
  expect(await dots()).toEqual({ visible: [0], filter: ['!', ['has', 'r0']] })
  await page.getByRole('slider', { name: 'Forecast hour after departure' }).fill('30.75')
  expect((await dots()).visible).toEqual([31])
})

test('labels a waypoint detour and shows its waypoint', async ({ page }) => {
  await mockApi(page, { scenario: 'detour' })
  await page.goto('/')
  await planTrip(page)
  await expect(routeCards(page)).toHaveCount(3)
  const detour = routeCards(page).filter({ hasText: 'Route C' })
  await expect(detour).toContainText('Detour option: TomTom truck routing through a waypoint placed by this app')
  await expect(page.getByText(/TomTom returned 2 distinct truck route\(s\)\. Route C is a detour/)).toBeVisible()
  await expect(page.getByText('Waypoint · C')).toBeVisible()
})

test('says so when three meaningful routes cannot be found', async ({ page }) => {
  await mockApi(page, { scenario: 'two_routes' })
  await page.goto('/')
  await planTrip(page)
  await expect(routeCards(page)).toHaveCount(2)
  await expect(page.getByText(/Only 2 meaningful route\(s\) could be found/)).toBeVisible()
})

test('validates the form before calling the API', async ({ page }) => {
  const calls = await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Find the safest route' }).click()
  await expect(page.getByText('Pick an origin from the list.')).toBeVisible()
  await expect(page.getByText('Pick a destination from the list.')).toBeVisible()

  await page.getByRole('button', { name: 'Denver → Salt Lake City' }).click()
  await page.getByLabel('Load weight (lb)').fill('90000')
  await page.getByRole('button', { name: 'Find the safest route' }).click()
  await expect(page.getByText("Load can't exceed 80,000 lb.")).toBeVisible()

  await page.getByLabel('Load weight (lb)').fill('-5')
  await page.getByRole('button', { name: 'Find the safest route' }).click()
  await expect(page.getByText('Enter the load weight in pounds.')).toBeVisible()
  expect(calls.plan).toBe(0)
})

test('shows provider failures clearly', async ({ page }) => {
  await mockApi(page, {
    planStatus: 502,
    planBody: { error: { code: 'routing_unavailable', message: 'The routing service did not respond.' } },
  })
  await page.goto('/')
  await planTrip(page)
  const alert = page.getByRole('alert')
  await expect(alert).toContainText("Couldn't plan this trip")
  await expect(alert).toContainText('The routing service did not respond.')
  await expect(routeCards(page)).toHaveCount(0)
})

test('maps server validation errors onto the form fields', async ({ page }) => {
  await mockApi(page, {
    planStatus: 400,
    planBody: {
      error: {
        code: 'invalid_request',
        message: 'Check the highlighted fields.',
        details: { departure_time: ['Departure must be within the next 7 days.'] },
      },
    },
  })
  await page.goto('/')
  await planTrip(page)
  await expect(page.getByText('Departure must be within the next 7 days.')).toBeVisible()
})

test('repeated submissions replace the results without duplicate requests', async ({ page }) => {
  // Long enough that the pending state is observable even on a loaded CI machine.
  const calls = await mockApi(page, { planDelayMs: 2000 })
  await page.goto('/')
  await planTrip(page)
  await expect(routeCards(page)).toHaveCount(3)
  await page.getByRole('button', { name: 'Find the safest route' }).click()
  await expect(page.getByRole('button', { name: 'Planning routes…' })).toBeDisabled()
  await expect(routeCards(page)).toHaveCount(3)
  expect(calls.plan).toBe(2)
})

test('refresh starts clean', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await planTrip(page)
  await expect(routeCards(page)).toHaveCount(3)
  await page.reload()
  await expect(routeCards(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Find the safest route' })).toBeEnabled()
})

test.describe('phone layout', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true })

  test('fits a 375 px screen with no horizontal scroll', async ({ page }) => {
    await mockApi(page)
    await page.goto('/')
    await planTrip(page)
    await expect(routeCards(page)).toHaveCount(3)
    await expect(page.getByRole('slider', { name: 'Forecast hour after departure' })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
