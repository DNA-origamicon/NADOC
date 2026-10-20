import { expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './scene_harness.js'

export const previewPath = '/api/design/features/deformation-preview'

// Execute the real server request, then hold its unmodified response. The explicit
// loseReply fault discards only delivery after publication; never fabricate success.
// Always release/remove the route, including assertion failures.
export async function withHeldResponse(page, pathname, action, { loseReply = false } = {}) {
  let release, acknowledge, reject, flight = null
  const gate = new Promise(resolve => { release = resolve })
  const ready = new Promise((resolve, fail) => { acknowledge = resolve; reject = fail })
  const match = url => url.pathname === pathname
  const handler = route => {
    if (flight) return route.continue()
    flight = (async () => {
      const response = await route.fetch()
      acknowledge({ response, body: route.request().postDataJSON() })
      await gate
      if (loseReply) await route.abort('failed')
      else await route.fulfill({ response })
    })()
    flight.catch(reject)
    return flight
  }
  await page.route(match, handler)
  try { return await action({ ready, release: async () => { release(); if (flight) await flight } }) }
  finally {
    release()
    // Complete the held handler before removing its route. Removing first can
    // auto-handle the request and mask an assertion with "already handled".
    try { if (flight) await flight }
    finally { await page.unroute(match, handler) }
  }
}

export async function withHistoryFixture({ page, request }, kind, run, seed = kind, { pauseRendering = false } = {}) {
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  if (!root) throw new Error('Use the isolated history launcher')
  const doc = `__e2e__history-${kind}`, headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page), writes = []
  page.on('request', req => {
    if (req.method() !== 'GET' && new URL(req.url()).pathname.startsWith('/api/design'))
      writes.push({ path: new URL(req.url()).pathname, body: req.postDataJSON() })
  })
  const checkpoint = async () => {
    const r = await request.get('http://127.0.0.1:8004/api/__e2e__/history/checkpoint', { headers })
    expect(r.ok()).toBe(true)
    return r.json()
  }
  const browser = () => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const api = await import('/src/api/client.js'), s = store.getState()
    return { design: s.currentDesign, geometry: s.currentGeometry, revision: api.currentRevisionWatermark() }
  })
  const display = () => page.evaluate(() => {
    const roots = window.__nadocTest.scene.children.filter(n => n.name === 'privateDeformationPreview')
    return { roots: roots.length, visible: roots.filter(n => n.visible).length }
  })
  const popup = page.locator('.tool-popup[data-tool-panel="deform-panel"]')
  const open = async (index = null) => {
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const response = page.waitForResponse(r => new URL(r.url()).pathname === previewPath)
    const edits = page.locator('[title="Edit this feature"]')
    await (index === null ? edits.last() : edits.nth(index)).click()
    expect((await response).ok()).toBe(true)
    await expect(popup).toBeVisible()
    return (await response).json()
  }
  const change = async (selector, value, matches = () => true) => {
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`
      && matches(r.request().postDataJSON().params))
    await page.locator(selector).fill(String(value)); await page.locator(selector).press('Tab')
    const r = await pending
    expect(r.ok()).toBe(true)
    await expect(page.locator('#def-apply-btn')).toBeEnabled()
    return { body: r.request().postDataJSON(), packet: await r.json() }
  }
  let primary = false
  try {
    const seeded = await request.post(`http://127.0.0.1:8004/api/__e2e__/history/seed/${seed}`, { headers })
    expect(seeded.ok()).toBe(true)
    await page.goto(`/?doc=${doc}&readiness=simulation`, { waitUntil: pauseRendering ? 'domcontentloaded' : 'load' })
    if (pauseRendering) {
      // Latency checks exclude GPU raster. Pause before waiting for the initial
      // design/save: software WebGL can otherwise monopolize fixture startup.
      await page.waitForFunction(() => {
        if (!window.__nadocTest) return false
        window.__nadocTest.pauseViewerRenderingForTest()
        return true
      })
    }
    await page.waitForFunction(() => window.__nadocTest?.store.getState().currentGeometry?.length > 0)
    await page.waitForFunction(() => !new URL(location.href).searchParams.has('readiness'))
    const file = path.join(root, 'workspace', `${doc}-release.nadoc`)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.getDesign()
      if (!await api.saveDesign(file)) throw new Error('Fixture save failed')
    }, file)
    const result = await run({ page, request, doc, headers, root, file, checkpoint, browser, display, popup, open, change, writes, errors })
    // Failure-injection cases must assert exact diagnostic identity before returning
    // their expected list. Normal cases still require an empty console.
    expect(errors).toEqual(result?.expectedConsoleErrors ?? [])
  } catch (error) { primary = true; throw error }
  finally {
    const failures = []
    try { await page.close() } catch (error) { failures.push(error) }
    try {
      const r = await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`, { timeout: 5000 })
      if (!r.ok()) throw new Error(`Cleanup HTTP ${r.status()}`)
    } catch (error) { failures.push(error) }
    if (failures.length && !primary) throw failures[0]
  }
}
