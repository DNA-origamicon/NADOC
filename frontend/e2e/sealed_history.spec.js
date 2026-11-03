import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const endpoint = 'http://127.0.0.1:8004/api'
const preview = '/api/design/features/deformation-preview'
test.skip(process.env.NADOC_HISTORY_E2E_SEALED !== '1', 'Requires explicit isolated sealed mode')

for (const kind of ['bend', 'twist']) test(`sealed ${kind} historical Open/Cancel/Apply`, async ({ page, request }) => {
  const doc = `__e2e__history-${kind}`, headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page), events = [], httpFailures = new Map()
  const started = Date.now()
  let step = 'seed', primary = false
  page.on('response', r => {
    if (r.status() >= 400) {
      const key = `${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`
      const bounded = httpFailures.has(key) || httpFailures.size < 64 ? key : 'overflow'
      httpFailures.set(bounded, (httpFailures.get(bounded) ?? 0) + 1)
    }
    if (r.status() >= 400 || new URL(r.url()).pathname.startsWith('/api/design')) {
      events.push(`${Date.now() - started}ms ${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`)
      if (events.length > 40) events.shift()
    }
  })
  const checkpoint = async () => {
    const r = await request.get(`${endpoint}/__e2e__/history/checkpoint`, { headers })
    expect(r.ok()).toBe(true)
    return r.json()
  }
  const browser = () => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const api = await import('/src/api/client.js'), s = store.getState()
    return { design: s.currentDesign, geometry: s.currentGeometry, revision: api.currentRevisionWatermark() }
  })
  const roots = () => page.evaluate(() => window.__nadocTest.scene.children
    .filter(n => n.name === 'privateDeformationPreview').length)
  try {
    const seeded = await request.post(`${endpoint}/__e2e__/history/seed/${kind}`, { headers })
    expect(seeded.ok()).toBe(true)
    expect((await seeded.json()).sealed).toBe(true)
    step = 'initial sealed adoption'
    await page.goto(`/?doc=${doc}&readiness=simulation`)
    await page.waitForFunction(() => window.__nadocTest?.store.getState().currentGeometry?.length > 0, null, { timeout: 15000 })
    step = 'readiness handoff completion'
    await page.waitForFunction(() => !new URL(location.href).searchParams.has('readiness'), null, { timeout: 15000 })
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const before = await checkpoint(), stored = await browser()
    expect(before.sealed).toBe(true)
    expect(before.redo).toHaveLength(1)
    const popup = page.locator('.tool-popup[data-tool-panel="deform-panel"]')
    const input = page.locator(kind === 'bend' ? '#def-bend-angle' : '#def-twist-value')
    const open = async () => {
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === preview)
      await page.locator('[title="Edit this feature"]').last().click()
      const opened = await pending
      expect(opened.ok(), `Open HTTP ${opened.status()}: ${(await opened.text()).slice(0, 2048)}`).toBe(true)
      await expect(popup).toBeVisible()
      await expect.poll(roots).toBe(2)
    }
    const change = async () => {
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === `${preview}/evaluate`)
      await input.fill('25'); await input.press('Tab')
      expect((await pending).ok()).toBe(true)
      await expect(page.locator('#def-apply-btn')).toBeEnabled()
    }
    step = 'Open/edit/Cancel'
    await open(); await change()
    const cancelled = page.waitForResponse(r => new URL(r.url()).pathname === `${preview}/cancel`)
    await page.locator('#def-cancel-btn').click()
    expect((await cancelled).ok()).toBe(true)
    await expect(popup).not.toBeVisible()
    await expect.poll(roots).toBe(0)
    expect(await checkpoint()).toEqual(before)
    expect(await browser()).toEqual(stored)
    step = 'Open/edit/Apply and adoption'
    await open(); await change()
    const applied = page.waitForResponse(r => new URL(r.url()).pathname === `${preview}/apply`)
    await page.locator('#def-apply-btn').click()
    const response = await applied, receiptAt = Date.now()
    expect(response.ok()).toBe(true)
    const receipt = await response.json()
    await expect(popup).not.toBeVisible()
    await expect.poll(roots).toBe(0)
    await expect.poll(async () => (await browser()).revision).toBe(receipt.revision)
    console.log(`[sealed-history] ${kind} Apply-to-adoption ${Date.now() - receiptAt}ms`)
    step = 'post-Apply state/geometry/proof/console'
    const after = await checkpoint(), adopted = await browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(adopted.design.deformations).toEqual(after.design.deformations)
    expect(adopted.design.feature_log).toEqual(after.design.feature_log)
    // Read through the desktop owner: an out-of-band HTTP client otherwise
    // creates contention that the page's passive scheduler cannot observe.
    const geometry = await page.evaluate(async () => {
      const { _request } = await import('/src/api/client.js')
      let failure = null
      const body = await _request('GET', '/design/geometry', undefined, {
        suppressBusy: true, onError: (status, detail) => { failure = { status, detail } },
      })
      return { body, failure }
    })
    expect(geometry.failure, 'Final geometry HTTP failure').toBeNull()
    expect(geometry.body, 'Final geometry response missing').not.toBeNull()
    expect(adopted.geometry).toEqual(geometry.body.nucleotides)
    const proof = await request.get(`${endpoint}/__e2e__/history/proof`, { headers })
    expect(proof.ok(), `Final proof HTTP ${proof.status()}: ${(await proof.text()).slice(0, 2048)}`).toBe(true)
    expect((await proof.json()).status).toBe('verified')
    console.log(`[sealed-history] ${kind} final state/geometry/proof passed`)
    expect(errors).toEqual([])
  } catch (error) {
    primary = true
    let diagnostic
    try {
      const state = await browser()
      const response = await request.get(`${endpoint}/__e2e__/history/checkpoint`, { headers, timeout: 3000 })
      const canonical = response.ok() ? await response.json() : {}
      diagnostic = { elapsedMs: Date.now() - started, browserRevision: state.revision,
        geometryCount: state.geometry?.length, canonicalRevision: canonical.revision,
        historyCount: canonical.history?.length, redoCount: canonical.redo?.length,
        privateRoots: await roots(), panel: (await page.locator('#deform-panel').textContent())?.slice(-800) }
    } catch (failure) { diagnostic = { error: failure.message.slice(0, 500) } }
    throw new Error(`${step}: ${error.message}\nDiagnostic: ${JSON.stringify(diagnostic)}\nEvents: ${JSON.stringify(events)}\nConsole: ${JSON.stringify(errors)}\nFailures: ${JSON.stringify(Object.fromEntries(httpFailures))}`)
  } finally {
    const failures = []
    try { await page.close() } catch (error) { failures.push(error) }
    try {
      const closed = await request.delete(`${endpoint}/__e2e__/history/close`, { headers, timeout: 5000 })
      if (!closed.ok()) throw new Error(`Fixture cleanup HTTP ${closed.status()}`)
    } catch (error) { failures.push(error) }
    if (failures.length && !primary) throw failures[0]
  }
})
