import { test, expect } from '@playwright/test'
import { readFileSync, writeFileSync, mkdirSync, existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const DOC = '__e2e__feature-seek-voltron'
const fixtureDir = `${ROOT}workspace/playwright_tests/${DOC}`
const fixture = `${fixtureDir}/${DOC}.nadoc`
const owned = [fixtureDir, `${ROOT}workspace/.session/${DOC}`, `${ROOT}workspace/.nadoc-projects/${DOC}`, `${ROOT}workspace/${DOC}.nadoc`]
const API = `${process.env.NADOC_E2E_API_BASE}/api`

// Persistence inventory: the only input copy lives in fixtureDir. Autosave can
// create the named workspace file and project store; afterEach and global
// teardown remove them. Isolated backend disables session-cache writes.
test.beforeAll(() => {
  for (const path of owned) expect(existsSync(path), `Pre-existing artifact ${path}`).toBe(false)
  const design = JSON.parse(readFileSync(`${ROOT}workspace/VoltronCoreArmV2.nadoc`, 'utf8'))
  design.id = DOC; design.metadata.name = DOC
  mkdirSync(fixtureDir, { recursive: true })
  writeFileSync(fixture, JSON.stringify(design))
})
test.afterEach(async ({ page, request }) => {
  try { await page.close(); await request.delete(`${API}/documents/${DOC}`) }
  finally {
    for (const path of owned) rmSync(path, { recursive: true, force: true })
    for (const path of owned) expect(existsSync(path)).toBe(false)
  }
})

test('Voltron scrub displays a preview, locks edits, then becomes editable', async ({ page, request }) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(15000)
  const errors = []
  page.on('pageerror', e => { errors.push(e.message); console.log('BROWSER_ERROR', e.message) })
  await page.goto(`/?doc=${DOC}&open=${encodeURIComponent(`playwright_tests/${DOC}/${DOC}.nadoc`)}`)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentGeometry?.length > 0, null, { timeout: 90000 })
  console.log('FEATURE_SEEK_LOADED', await page.evaluate(() => ({
    error: window.__nadocTest.store.getState().lastError,
    nucleotides: window.__nadocTest.store.getState().currentGeometry.length,
  })))
  await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  await expect(page.locator('#fl-list [data-fl-row]').first()).toBeAttached()
  // Record scene/readiness timing every rendered frame, including short previews.
  await page.evaluate(() => {
    window.__seekFrames = []
    const sample = () => {
      const t = window.__nadocTest
      window.__seekFrames.push({ time: performance.now(), preview: !!t.scene.getObjectByName('feature-seek-preview'),
        pending: !!t.store.getState().featureSeekPending, cursor: t.store.getState().currentDesign.feature_log_cursor })
      if (!window.__seekSamplingDone) requestAnimationFrame(sample)
    }
    requestAnimationFrame(sample)
  })
  const seek = async rowIndex => {
    await page.evaluate(index => {
      const thumb = document.querySelector('#fl-rail .feature-seek-readiness').parentElement
      const row = document.querySelectorAll('#fl-list [data-fl-row]')[index]
      const box = row.getBoundingClientRect()
      window.__seekStart = performance.now()
      thumb.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientY: box.top, pointerId: 1 }))
      document.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientY: box.top + box.height / 2, pointerId: 1 }))
      document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 }))
    }, rowIndex)
  }
  await seek(55)
  await expect(page.locator('#fl-rail [data-readiness="loading"]')).toBeAttached()
  await page.waitForFunction(() => !!window.__nadocTest.scene.getObjectByName('feature-seek-preview'))
  const preview = await page.evaluate(async () => {
    const t = window.__nadocTest
    const api = await import('/src/api/client.js')
    const root = t.scene.getObjectByName('feature-seek-preview')
    const pixels = t.renderedPixelCensus()
    root.visible = false
    const hiddenPixels = t.renderedPixelCensus()
    root.visible = true
    return { elapsed: performance.now() - window.__seekStart,
      instances: t.scene.getObjectByName('feature-seek-preview').children[0].count,
      pixels, hiddenPixels,
      blockedEdit: await api._request('POST', '/design/undo') }
  })
  expect(preview.instances).toBeGreaterThan(0)
  expect(preview.pixels.visible).toBeGreaterThan(preview.hiddenPixels.visible + 50)
  expect(preview.blockedEdit).toBeNull()
  await expect(page.locator('#fl-rail [data-readiness="ready"]')).toBeAttached({ timeout: 60000 })
  const ready = await page.evaluate(() => ({ elapsed: performance.now() - window.__seekStart,
    cursor: window.__nadocTest.store.getState().currentDesign.feature_log_cursor,
    preview: !!window.__nadocTest.scene.getObjectByName('feature-seek-preview') }))
  expect(ready.cursor).toBe(54)
  expect(ready.preview).toBe(false)
  await seek(109)
  await expect(page.locator('#fl-rail [data-readiness="ready"]')).toBeAttached({ timeout: 60000 })
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log_cursor)).toBe(-1)
  const finalStage = await page.evaluate(() => ({ elapsed: performance.now() - window.__seekStart,
    cursor: window.__nadocTest.store.getState().currentDesign.feature_log_cursor }))
  console.log('FEATURE_SEEK_VISUAL_TIMING', JSON.stringify({ preview, ready, finalStage }))
  await page.evaluate(() => { window.__seekSamplingDone = true })
  expect(errors).toEqual([])
})
