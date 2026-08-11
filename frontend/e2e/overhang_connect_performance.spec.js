import { test, expect } from '@playwright/test'

const FIXTURE = '/home/joshua/NADOC/workspace/VoltronCoreArm.nadoc'
const OH49 = 'ovhg_h_XY_16_27_72_5p'
const OH50 = 'ovhg_h_sc_48_72_3p'

test('VoltronCoreArm OH49/OH50 root-to-root Connect timing', async ({ page }, testInfo) => {
  test.setTimeout(240_000)
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.evaluate(async (path) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)

  const requests = []
  let connectPayload = null
  const starts = new Map()
  page.on('request', req => {
    if (req.url().includes('/api/')) starts.set(req, performance.now())
  })
  page.on('response', async res => {
    const req = res.request()
    if (!starts.has(req)) return
    requests.push({
      method: req.method(),
      path: new URL(req.url()).pathname + new URL(req.url()).search,
      status: res.status(),
      milliseconds: performance.now() - starts.get(req),
      serverTiming: await res.headerValue('server-timing'),
    })
    if (req.method() === 'POST' && req.url().includes('/connection-versions/connect')) {
      connectPayload = await res.json()
    }
  })

  await page.evaluate(([a, b]) => {
    document.getElementById('oconn-heading').click()
    const sa = document.getElementById('oconn-select-a')
    const sb = document.getElementById('oconn-select-b')
    sa.value = a; sa.dispatchEvent(new Event('change'))
    sb.value = b; sb.dispatchEvent(new Event('change'))
    document.getElementById('oconn-button-box').click()
    document.querySelector('#oconn-popover [data-variant="root-to-root"]').click()
  }, [OH49, OH50])
  await expect(page.locator('#oconn-generate')).toHaveText('Connect')
  expect(await page.locator('#oconn-generate').isDisabled()).toBe(false)

  const t0 = performance.now()
  await page.evaluate(() => document.getElementById('oconn-generate').click())
  await expect(page.locator('#oconn-list .oconn-version-row')).toHaveCount(1, { timeout: 90_000 })
  const fullyRenderedMs = performance.now() - t0

  const state = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    return {
      versions: d.connection_versions?.length ?? 0,
      bindings: d.overhang_bindings?.length ?? 0,
      duplexes: d.duplexes?.length ?? 0,
    }
  })
  expect(state).toEqual({ versions: 1, bindings: 1, duplexes: 1 })

  const report = { fullyRenderedMs, requests, state }
  await testInfo.attach('connect-timing.json', {
    body: JSON.stringify(report, null, 2), contentType: 'application/json',
  })
  console.log(`[OH49/OH50 Connect] ${fullyRenderedMs.toFixed(0)}ms`, JSON.stringify(requests))

  // One atomic mutation only: no follow-up geometry or duplex requests.
  const mutating = requests.filter(r => r.method !== 'GET')
  expect(mutating.map(r => r.path)).toEqual(['/api/design/connection-versions/connect'])
  expect(connectPayload?.partial_geometry).toBe(true)
  expect(connectPayload?.changed_helix_ids).toHaveLength(6)
  const geometryFetches = requests.filter(r => r.path.includes('/design/geometry'))
  expect(geometryFetches.length).toBeLessThanOrEqual(1)
  if (geometryFetches.length) expect(geometryFetches[0].path).toContain('apply_deformations=false')
  // Dedicated-host Chromium gate: loose enough for CI variance, strict enough
  // to catch the original repeated full-geometry/rebuild cascade.
  expect(fullyRenderedMs).toBeLessThan(60_000)
})
