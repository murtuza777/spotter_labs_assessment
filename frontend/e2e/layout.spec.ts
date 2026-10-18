import { expect, test, type Page } from '@playwright/test'
import { mockApi, planTrip, routeCards, waitForMapLayers } from './helpers'

async function planned(page: Page) {
  const calls = await mockApi(page)
  await page.goto('/')
  await planTrip(page)
  await expect(routeCards(page)).toHaveCount(3)
  await waitForMapLayers(page)
  await page.waitForFunction(() => !(window as any).__map.isMoving(), null, { timeout: 10_000 })
  return calls
}

/** Pan so the selected route's 5th checkpoint sits `inset` px from one edge; return its page position. */
async function placeCheckpointAt(page: Page, edge: 'left' | 'right' | 'top' | 'bottom', inset = 28) {
  await page.waitForFunction(() => !(window as any).__map.isMoving())
  return page.evaluate(
    ([edge, inset]) => {
      const map = (window as any).__map
      const [feature] = map.queryRenderedFeatures({ layers: ['checkpoints'] }).filter((f: any) => f.properties.index === 5)
      const lngLat = feature.geometry.coordinates
      const { width, height } = map.getContainer().getBoundingClientRect()
      const target = {
        left: [inset, height / 2],
        right: [width - inset, height / 2],
        top: [width / 2, inset],
        bottom: [width / 2, height - inset],
      }[edge as string]!
      const now = map.project(lngLat)
      map.panBy([now.x - target[0], now.y - target[1]], { duration: 0 })
      const p = map.project(lngLat)
      const rect = map.getContainer().getBoundingClientRect()
      return { x: rect.left + p.x, y: rect.top + p.y }
    },
    [edge, inset] as const,
  )
}

test('checkpoint popups stay inside the map near every edge', async ({ page }) => {
  await planned(page)
  for (const edge of ['left', 'right', 'top', 'bottom'] as const) {
    const at = await placeCheckpointAt(page, edge)
    await page.mouse.click(at.x, at.y)
    // Clicking a checkpoint that is already on screen must not move the map.
    expect(await page.evaluate(() => (window as any).__map.isMoving())).toBe(false)
    const popup = page.locator('.maplibregl-popup')
    await expect(popup).toContainText('Route B · mile')
    const inside = await page.evaluate(() => {
      const p = document.querySelector('.maplibregl-popup')!.getBoundingClientRect()
      const m = document.querySelector('.maplibregl-map')!.getBoundingClientRect()
      return { left: p.left - m.left, right: m.right - p.right, top: p.top - m.top, bottom: m.bottom - p.bottom }
    })
    for (const [side, gap] of Object.entries(inside)) expect(gap, `${edge} edge: ${side} gap`).toBeGreaterThanOrEqual(0)
    // Escape closes it, from the keyboard, wherever focus is.
    await page.keyboard.press('Escape')
    await expect(popup).toHaveCount(0)
  }
})

test('route cards are keyboard-operable and switching routes makes no requests', async ({ page }) => {
  const calls = await planned(page)
  const routeC = routeCards(page).filter({ hasText: 'Route C' })
  await routeC.focus()
  await page.keyboard.press('Enter')
  await expect(routeC).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Route C checkpoints')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Forecast timeline' })).toContainText('Route C')
  for (const metric of ['Wind', 'Rain', 'Snow', 'Risk']) await page.getByRole('button', { name: metric, exact: true }).click()
  expect(calls.plan).toBe(1)
  expect(calls.heatmap).toBe(1)
})

for (const width of [320, 430, 768, 1024, 1280, 1920]) {
  test(`no horizontal page overflow at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 768 ? 800 : 900 })
    await planned(page)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
    // Nothing interactive is cut off at the right edge.
    const clipped = await page.evaluate(() =>
      [...document.querySelectorAll('button, input, select, a')]
        .map((el) => el.getBoundingClientRect())
        .filter((r) => r.width > 0 && r.right > window.innerWidth + 1).length,
    )
    expect(clipped).toBe(0)
  })
}

test.describe('phone', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true })

  test('checkpoint details dock inside the map and close', async ({ page }) => {
    await planned(page)
    await page.getByRole('button', { name: /^mi 50\b/ }).click()
    const details = page.getByRole('region', { name: 'Checkpoint details' })
    await expect(details).toBeVisible()
    await expect(details).toContainText('Route B · mile 50')
    await expect(details).toBeInViewport() // the page scrolled the map back into view
    const box = (await details.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(375)
    await details.getByRole('button', { name: 'Close checkpoint details' }).tap()
    await expect(details).toHaveCount(0)
  })

  test('primary controls are comfortable touch targets', async ({ page }) => {
    await planned(page)
    const heights = await page.evaluate(() => {
      const h = (el: Element | null) => (el ? Math.round(el.getBoundingClientRect().height) : 0)
      return {
        editTrip: h([...document.querySelectorAll('button')].find((b) => b.textContent?.includes('Edit trip')) ?? null),
        play: h(document.querySelector('[aria-label="Play forecast animation"]')),
        slider: h(document.querySelector('input[type="range"]')),
        metric: h([...document.querySelectorAll('button')].find((b) => b.textContent === 'Wind') ?? null),
        checkpoint: h([...document.querySelectorAll('button')].find((b) => b.textContent?.startsWith('mi 25')) ?? null),
        zoom: h(document.querySelector('[aria-label="Zoom in"]')),
      }
    })
    for (const [control, height] of Object.entries(heights)) expect(height, control).toBeGreaterThanOrEqual(40)
    expect(heights.slider).toBeGreaterThanOrEqual(44)
  })
})

test('honours reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockApi(page)
  await page.goto('/')
  await planTrip(page)
  await expect(routeCards(page)).toHaveCount(3)
  await waitForMapLayers(page, false)
  // The camera jumps to the routes instead of animating, and CSS transitions are suppressed.
  expect(await page.evaluate(() => (window as any).__map.isMoving())).toBe(false)
  const duration = await routeCards(page).first().evaluate((el) => getComputedStyle(el).transitionDuration)
  expect(parseFloat(duration)).toBeLessThan(0.001)
})
