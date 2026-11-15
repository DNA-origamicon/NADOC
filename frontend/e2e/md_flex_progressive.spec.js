import { test, expect } from '@playwright/test'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Read an existing part only. No design/job save endpoints are used. Session
// cache is disabled in Playwright config; afterEach defensively removes our
// exact session path. Global teardown removes the isolated Vite credential,
// and the configured artifact reporter removes screenshots/traces on failure.
const root = fileURLToPath(new URL('../../', import.meta.url))
const doc = '__e2e__flex-progressive'
const source = `${root}workspace/${process.env.NADOC_FLEX_AUDIT_SOURCE || "2hb_2xT.nadoc"}`
const session = `${root}workspace/.session/${doc}`
let original

test.beforeEach(() => {
  test.skip(!existsSync(source), 'Requires an existing read-only design')
  expect(existsSync(session)).toBe(false)
  original = readFileSync(source)
})
test.afterEach(async ({ page, request }) => {
  if (!original) return
  try {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api/documents/${doc}`)
  } finally {
    rmSync(session, { force: true, recursive: true })
    expect(existsSync(session)).toBe(false)
    expect(readFileSync(source).equals(original)).toBe(true)
  }
})

test('last-chunk map is visible before final response and stopping restores native positions', async ({ page }) => {
  test.setTimeout(90000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`/?debug=1&doc=${doc}`)
  await page.waitForFunction(() => window.__nadocTest && window.__nadocMdViz)
  const positions = await page.evaluate(async source => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(source)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const { store } = await import('/src/state/store.js')
    const geometry = store.getState().currentGeometry
    return geometry.nucleotides ?? geometry
  }, source)
  expect(positions.length).toBeGreaterThan(0)
  const payload = (offset, preliminary) => ({ ready: true, preliminary, n_frames: preliminary ? 32 : 100,
    min_rmsf: 0, max_rmsf: 1, mean_rmsf: .5,
    positions: positions.map(p => ({ ...p, nx: 1, ny: 0, nz: 0, rmsf: .5, backbone_position: p.backbone_position.map((v, i) => v + (i === 0 ? offset : 0)) })) })
  let release
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/md/jobs/__e2e__flex/rmsf', async route => {
    await gate
    await route.fulfill({ json: payload(2, false) }).catch(() => {})
  })
  await page.route('**/api/md/jobs/__e2e__flex/display', route => route.fulfill({ json: { ready: true } }))
  await page.route('**/api/md/jobs/__e2e__flex/flex-progress?*', route => route.fulfill({ json: {
    active: true, frame_range: null, phase: 'tail_preview', done: 32, total: 100, revision: 1, partial: payload(1, true),
  } }))
  await page.evaluate(() => {
    window.__flexDone = false
    window.__flexPending = window.__nadocMdViz.displayRmsf('__e2e__flex').then(r => {
      window.__flexDone = true
      return r
    })
  })
  await expect.poll(() => page.evaluate(() => window.__nadocMdViz.mode())).toBe('rmsf')
  expect(await page.evaluate(() => window.__flexDone)).toBe(false)
  expect(await page.evaluate(() => window.__nadocTest.getDesignRenderer().getFemPositions().length)).toBe(positions.length)
  expect(await page.evaluate(() => window.__nadocTest.getDesignRenderer().getFemPositions()[0].backbone_position[0])).toBeCloseTo(positions[0].backbone_position[0] + 1)
  release()
  await expect.poll(() => page.evaluate(() => window.__flexDone)).toBe(true)
  expect(await page.evaluate(() => window.__flexPending)).toMatchObject({ ok: true, nFrames: 100 })
  expect(await page.evaluate(() => window.__nadocTest.getDesignRenderer().getFemPositions()[0].backbone_position[0])).toBeCloseTo(positions[0].backbone_position[0] + 2)
  await page.evaluate(() => window.__nadocMdViz.stopAndRestore())
  expect(await page.evaluate(() => window.__nadocTest.getDesignRenderer().getFemPositions())).toBeNull()
  expect(errors).toEqual([])
})

test('flex settings Apply selects frames and preliminary mapping exposes working color controls', async ({ page }) => {
  test.setTimeout(90000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let job = null, positions = [], release, received = null
  const gate = new Promise(resolve => { release = resolve })
  const id = '__e2e__flex-settings'
  const selection = { start: 101, end: 500, interval: 2 }
  const payload = preliminary => ({ ready: true, preliminary, n_frames: preliminary ? 32 : 200,
    min_rmsf: 0, max_rmsf: 1, mean_rmsf: .5,
    positions: positions.map(p => ({ ...p, nx: 1, ny: 0, nz: 0, rmsf: .5,
      backbone_position: p.backbone_position.map((v, i) => v + (i === 0 ? 1 : 0)) })) })
  await page.route(/\/api\/md\/jobs(?:\?.*)?$/, route => route.fulfill({ json: job ? [job] : [] }))
  await page.route(`**/api/md/jobs/${id}**`, async route => {
    const url = new URL(route.request().url()), suffix = url.pathname.split(id)[1]
    if (suffix === '/rmsf') {
      received = Object.fromEntries(url.searchParams)
      await gate
      return route.fulfill({ json: payload(false) }).catch(() => {})
    }
    if (suffix === '/flex-progress') return route.fulfill({ json: {
      active: true, frame_range: selection, phase: 'tail_preview', done: 32, total: 200,
      revision: 1, partial: payload(true),
    } })
    if (suffix === '/trajectory-meta') return route.fulfill({ json: {
      ready: true, total_raw: 1000, stages: [{ n_raw: 1000 }], n_frames: 50,
    } })
    return route.fulfill({ json: suffix === '' ? job : { ready: false } })
  })
  await page.goto(`/?debug=1&doc=${doc}`)
  await page.waitForFunction(() => window.__nadocTest && window.__nadocMdPanel)
  const loaded = await page.evaluate(async source => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(source)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(button => { button.disabled = false })
    window.__leftSidebar?.refresh?.()
    const { store } = await import('/src/state/store.js')
    const state = store.getState()
    return { design: state.currentDesign.id, positions: state.currentGeometry }
  }, source)
  positions = loaded.positions
  job = { job_id: id, design_id: loaded.design, design_name: 'Flex settings check',
    status: 'completed', created_at: 1, execution_target: 'local', segments: [] }
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(async id => { await window.__nadocMdPanel.refresh(); await window.__nadocMdPanel.selectJob(id) }, id)
  if (!await page.locator('#md-jobs-viz-toggle').isVisible()) await page.locator('#md-jobs-panel-heading').click()
  if (!await page.locator('#md-jobs-flex-settings').isVisible()) await page.locator('#md-jobs-viz-toggle').click()
  await page.locator('#md-jobs-flex-settings').click()
  const dialog = page.getByRole('dialog', { name: 'Flexibility map settings' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('Start', { exact: true })).toHaveValue('801')
  await expect(dialog.getByLabel('End', { exact: true })).toHaveValue('1000')
  await expect(dialog.getByLabel('Interval', { exact: true })).toHaveValue('1')
  await dialog.getByLabel('Start', { exact: true }).fill('1')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  expect(received).toBeNull()
  await page.locator('#md-jobs-flex-settings').click()
  await expect(dialog.getByLabel('Start', { exact: true })).toHaveValue('801')
  for (const [key, value] of Object.entries(selection)) {
    await dialog.getByLabel(key[0].toUpperCase() + key.slice(1), { exact: true }).fill(String(value))
  }
  await dialog.getByRole('button', { name: 'Apply' }).click()
  await expect(dialog).not.toBeVisible()
  await expect.poll(() => received).toEqual({ start: '101', end: '500', interval: '2' })
  await expect(page.locator('#flex-scale')).toBeVisible()
  await expect(page.locator('#md-jobs-flex-legend')).toBeVisible()
  await page.locator('#flex-scale-min').fill('0.2')
  await page.locator('#flex-scale-min').press('Enter')
  expect(await page.evaluate(() => window.__nadocMdViz.coloringInfo().lo)).toBeCloseTo(.2)
  release()
  await expect(page.locator('#md-jobs-flex-status')).toContainText('200 frames')
  expect(await page.evaluate(() => window.__nadocMdViz.coloringInfo().lo)).toBeCloseTo(.2)
  await page.evaluate(() => window.__nadocMdViz.stopAndRestore())
  expect(errors).toEqual([])
})
