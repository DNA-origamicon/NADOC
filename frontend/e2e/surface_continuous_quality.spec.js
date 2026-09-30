import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, rmSync, mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DOC = '__e2e__surface-continuous'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const ownedPaths = [`.session/${DOC}`, `.nadoc-projects/${DOC}`, `playwright_tests/${DOC}.nadoc`]
  .map(path => `${ROOT}workspace/${path}`)
// Purposeful review evidence retained outside the user's workspace.
const evidence = `${ROOT}.development-artifacts/surface-final-figure`
let fixture

test.beforeAll(() => {
  for (const path of ownedPaths) expect(existsSync(path)).toBe(false)
  fixture = JSON.parse(execFileSync('uv', ['run', 'python', '-c', `
from tests.conftest import make_6hb_design
import json
d=make_6hb_design(24);d.id='${DOC}';d.metadata.name='${DOC}'
print(json.dumps(d.model_dump_json()))
`], { cwd: ROOT, encoding: 'utf8' }))
  mkdirSync(evidence, { recursive: true })
})

test.afterEach(async ({ page, request }) => {
  try {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${DOC}`)
  } finally {
    for (const path of ownedPaths) rmSync(path, { recursive: true, force: true })
    for (const path of ownedPaths) expect(existsSync(path)).toBe(false)
  }
})

test('figure quality uses measured progress and opaque defaults', async ({ page }) => {
  test.setTimeout(180000)
  const errors = [], snapshots = [], pendingSnapshots = []
  let bytes = null, progressId = null
  const requestedDetails = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', m => { if (m.type() === 'error' && /WebGL|shader/i.test(m.text())) errors.push(m.text()) })
  page.on('response', response => {
    if (response.url().includes('/api/surface-progress/') && response.status() === 200) {
      pendingSnapshots.push(response.json().then(value => snapshots.push(value)).catch(() => {}))
    }
  })
  await page.route('**/api/design/surface-bin?*', async route => {
    requestedDetails.push(new URL(route.request().url()).searchParams.get('detail'))
    progressId = route.request().headers()['x-nadoc-surface-progress']
    const response = await route.fetch({ timeout: 120000 })
    bytes = await response.body()
    await route.fulfill({ response, body: bytes })
  })
  await page.goto(`/?doc=${DOC}`)
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async content => {
    window.__surfaceProgressEvents = []
    window.addEventListener('nadoc:op-progress', e => window.__surfaceProgressEvents.push(e.detail))
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
  }, fixture)
  await expect(page.locator('#sl-surface-probe')).toHaveValue('0.06')
  await expect(page.locator('#sl-surface-opacity')).toHaveJSProperty('valueAsNumber', 1)
  await expect(page.locator('#cb-surface-remesh')).toHaveCount(0)
  const response = page.waitForResponse(r => r.url().includes('/api/design/surface-bin?') && r.status() === 200)
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  const surfaces = page.locator('#right-representation-modes .right-repr-btn').filter({ hasText: /^(Quick|Detail) Surface$/ })
  await expect(surfaces).toHaveCount(2)
  const boxes = await surfaces.evaluateAll(buttons => buttons.map(b => b.getBoundingClientRect().toJSON()))
  expect(boxes[0].y).toBe(boxes[1].y)
  await page.locator('#right-representation-modes [data-target="menu-view-surface-detail"]').click()
  await expect(page.locator('#op-progress')).toHaveClass(/visible/)
  await expect(page.locator('#op-progress-header')).toHaveText('Computing surface…')
  await response
  expect(progressId).toBeTruthy()
  expect(requestedDetails).toEqual(['chimerax'])
  await expect(page.locator('#cb-surface-figure-quality')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => {
    const m = window.__nadocTest.scene.getObjectByName('dna-surface')
    return m?.visible ? (m.geometry.index?.count ?? m.geometry.attributes.position.count) / 3 : 0
  }), { timeout: 30000 }).toBe(bytes.readUInt32LE(8))
  await expect(page.locator('#op-progress')).not.toHaveClass(/visible/)
  await Promise.all(pendingSnapshots)
  expect(snapshots.length).toBeGreaterThan(0)
  const events = await page.evaluate(() => window.__surfaceProgressEvents)
  writeFileSync(`${evidence}/progress.json`, JSON.stringify({ snapshots, events }, null, 2))
  const measured = snapshots.filter(s => Number.isFinite(s.done) && s.total > 0)
  expect(measured.length).toBeGreaterThan(0)
  expect(measured.some(s => events.some(e => e.action === 'update' && e.label.includes(s.stage) && Math.abs(parseFloat(e.fraction) - 100 * s.done / s.total) < .001))).toBe(true)
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [4, 4, 24], target: [4, 4, 4] }))
  const census = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
  expect(census.visible).toBeGreaterThan(100)
  expect(census.colorful).toBeGreaterThan(100)
  const opacity = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().surfaceOpacity)
  expect(opacity).toBe(1)
  await page.screenshot({ path: `${evidence}/figure.png` })
  expect(errors).toEqual([])
  console.log('FIGURE_PROGRESS_APP', JSON.stringify({ bytes: bytes.length, snapshots, events, census, opacity }))
})
