import { test } from '@playwright/test'
import { mockApi, planTrip, routeCards, waitForMapLayers } from './helpers'

// Visual review, not an assertion suite: captures the app at the target viewports with the
// real basemap and fixture API responses. Skipped unless SCREENSHOTS is set:
//   SCREENSHOTS=baseline npx playwright test screenshots
// Images land in frontend/screenshots/<SCREENSHOTS>/ (gitignored).
const RUN = process.env.SCREENSHOTS

/** Wait until the live basemap has finished loading tiles, so captures aren't half-drawn. */
async function settle(page: import('@playwright/test').Page) {
  await page.waitForFunction(() => { const m = (window as any).__map; return m && !m.isMoving() && m.areTilesLoaded() }, null, { timeout: 20_000 })
  await page.waitForTimeout(600)
}

const VIEWPORTS = [
  { name: '320x568-phone', width: 320, height: 568, mobile: true },
  { name: '375x812-phone', width: 375, height: 812, mobile: true },
  { name: '430x932-phone', width: 430, height: 932, mobile: true },
  { name: '844x390-phone-landscape', width: 844, height: 390, mobile: true },
  { name: '768x1024-tablet', width: 768, height: 1024, mobile: true },
  { name: '1024x768-tablet-landscape', width: 1024, height: 768, mobile: true },
  { name: '1280x800-laptop', width: 1280, height: 800, mobile: false },
  { name: '1440x900-desktop', width: 1440, height: 900, mobile: false },
  { name: '1920x1080-desktop', width: 1920, height: 1080, mobile: false },
]

for (const vp of VIEWPORTS) {
  test.describe(vp.name, () => {
    test.skip(!RUN, 'set SCREENSHOTS=<label> to capture')
    test.use({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile })

    test('capture', async ({ page }) => {
      test.setTimeout(90_000)
      const dir = `screenshots/${RUN}/${vp.name}`
      await mockApi(page, { basemap: 'live', planDelayMs: 100 })
      await page.goto('/')
      await page.waitForTimeout(1500)
      await page.screenshot({ path: `${dir}-1-empty.png` })

      await planTrip(page)
      await routeCards(page).first().waitFor()
      await waitForMapLayers(page)
      await page.waitForFunction(() => !(window as any).__map.isMoving(), null, { timeout: 10_000 })
      await settle(page)
      await page.screenshot({ path: `${dir}-2-plan.png` })
      await page.screenshot({ path: `${dir}-3-plan-full.png`, fullPage: true })

      // Open a checkpoint from the list, as a touch user would.
      const row = page.getByRole('button', { name: /^mi \d+/ }).nth(3)
      await row.scrollIntoViewIfNeeded()
      await row.click()
      await settle(page)
      await page.screenshot({ path: `${dir}-4-checkpoint.png` })
      const overflow = await page.evaluate(() => {
        const doc = document.documentElement.scrollWidth - window.innerWidth
        const popup = document.querySelector('.maplibregl-popup')?.getBoundingClientRect()
        const map = document.querySelector('.maplibregl-map')?.getBoundingClientRect()
        return {
          page: doc,
          popup: popup && map
            ? { left: Math.round(popup.left - map.left), right: Math.round(map.right - popup.right), top: Math.round(popup.top - map.top), bottom: Math.round(map.bottom - popup.bottom) }
            : null,
        }
      })
      console.log(vp.name, JSON.stringify(overflow))
    })
  })
}

// The other page states, at a phone and a desktop width.
const STATES = [
  { name: 'partial', opts: { scenario: 'partial_forecast' as const } },
  { name: 'outage', opts: { scenario: 'weather_outage' as const } },
  { name: 'no-safe-route', opts: { scenario: 'no_safe_route' as const } },
  { name: 'loading', opts: { planDelayMs: 60_000 } },
  {
    name: 'error',
    opts: { planStatus: 502, planBody: { error: { code: 'routing_unavailable', message: 'The routing service did not respond.' } } },
  },
]
for (const vp of [VIEWPORTS[1], VIEWPORTS[7]]) {
  for (const state of STATES) {
    test(`${vp.name} state ${state.name}`, async ({ page }) => {
      test.skip(!RUN, 'set SCREENSHOTS=<label> to capture')
      test.setTimeout(90_000)
      await page.setViewportSize({ width: vp.width, height: vp.height })
      await mockApi(page, { basemap: 'live', planDelayMs: 100, ...state.opts })
      await page.goto('/')
      await planTrip(page)
      await page.waitForTimeout(state.name === 'loading' ? 4000 : 2500)
      await page.screenshot({ path: `screenshots/${RUN}/state-${state.name}-${vp.name}.png`, fullPage: vp.mobile })
    })
  }
}
