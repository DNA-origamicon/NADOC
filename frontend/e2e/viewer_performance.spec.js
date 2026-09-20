import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { bridgeCredentialsPath, BRIDGE_PATH } from '../viewer_test_server.js'

// Persistence inventory: loadScaffoldedPart creates __e2e__viewer_perf*.nadoc
// and its project revision store. Existing global-teardown removes both, even on
// failure. No recordings/downloads/new artifact directories are created here.
test('captures rendered frames through Process Log and restores orbit controls', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__viewer_perf', name: 'viewer_perf' })
  const before = await page.evaluate(async () => {
    const { getViewerPerformance } = await import('/src/perf/viewer_performance.js')
    return { busy: getViewerPerformance().busy }
  })
  expect(before.busy).toBe(false)
  async function openLog() {
    await page.evaluate(async () => (await import('/src/ui/process_log.js')).openProcessLog())
    await page.locator('.viewer-performance-controls summary').click()
  }
  await openLog()
  await page.locator('[data-perf-seconds]').fill('1')
  await page.locator('[data-perf-start]').click()
  await expect(page.locator('#process-log')).toHaveCount(0)
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/perf/viewer_performance.js')).getViewerPerformance().latest?.valid)).toBe(true)
  await openLog()
  const text = await page.locator('[data-perf-output]').inputValue()
  expect(text).toContain('[NADOC_VIEWER_PERF v1]')
  const record = JSON.parse(text.slice(text.indexOf('{')))
  expect(record.frame_intervals.samples).toBeGreaterThan(1)
  expect(record.frame_intervals.p95_ms).toBeGreaterThan(0)
  expect(record.build.frontend_sha256).toMatch(/^[a-f0-9]{64}$/)
  expect(record.fixture_sha256).toMatch(/^[a-f0-9]{64}$/)
  expect(record.gpu_memory_bytes).toBeNull()
  // Software rasterization is a behavior check, not a user-hardware performance claim.
  console.log(`[viewer capture smoke] ${JSON.stringify({ samples: record.frame_intervals.samples, valid: record.valid })}`)
  expect(errors).toEqual([])
})

// Additional persistence: the Vite plugin creates a mode-0600 credential file in
// the OS temp directory, removed on server close. Results/snapshots stay in memory.
test('local API loads a native file, drives rendering, and retrieves nonblank pixels', async ({ page, request, baseURL }) => {
  test.setTimeout(60000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__viewer_bridge', name: 'viewer_bridge' })
  const design = await (await request.get(`${process.env.NADOC_E2E_API_BASE}/api/design`, { headers: { 'X-NADOC-Doc': '__e2e__viewer_bridge' } })).json()
  const filename = '__e2e__viewer_bridge_load.nadoc'
  await writeFile(resolve(process.cwd(), '../workspace', filename), JSON.stringify(design.design))
  // The file and any normal loader autosaves use __e2e__; global teardown removes
  // their project stores too. The named headless doc uses the cache-disabled backend.
  const headless = await promisify(execFile)('python3', [resolve(process.cwd(), '../scripts/nadoc_load.py'), '--api', process.env.NADOC_E2E_API_BASE, '--doc', '__e2e__viewer_headless', '--file', filename])
  expect(JSON.parse(headless.stdout).kind).toBe('part')
  // Reload empties the browser; the controller must load it without a file dialog.
  await page.reload()
  await page.waitForFunction(async () => !!(await import('/src/perf/viewer_performance.js')).getViewerPerformance())
  const framePart = () => page.evaluate(() => {
    const entries = window.__nadocTest.getDesignRenderer().getBackboneEntries()
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
    for (const entry of entries) {
      const position = entry.nuc?.backbone_position
      if (position) for (let axis = 0; axis < 3; axis++) { lo[axis] = Math.min(lo[axis], position[axis]); hi[axis] = Math.max(hi[axis], position[axis]) }
    }
    const target = lo.map((value, axis) => (value + hi[axis]) / 2)
    const distance = Math.max(...hi.map((value, axis) => value - lo[axis])) * 2 + 10
    window.__nadocTest.applyCameraPoseForTest({ position: [target[0] + distance, target[1] + distance * 0.4, target[2] + distance], target, up: [0, 1, 0], fov: 55 })
  })
  const { token } = JSON.parse(await readFile(bridgeCredentialsPath(resolve(process.cwd()), Number(new URL(baseURL).port)), 'utf8'))
  const headers = { Authorization: `Bearer ${token}` }
  let session
  await expect.poll(async () => {
    const sessions = await (await request.get(`${BRIDGE_PATH}/sessions`, { headers })).json()
    session = sessions[0]?.id
    return sessions.length
  }).toBe(1)
  async function command(action, options = {}) {
    const response = await request.post(`${BRIDGE_PATH}/commands`, { headers, data: { session, action, options } })
    expect(response.ok(), await response.text()).toBe(true)
    const { id } = await response.json()
    let job
    await expect.poll(async () => {
      job = await (await request.get(`${BRIDGE_PATH}/jobs/${id}`, { headers })).json()
      return job.status
    }, { timeout: 15000 }).toBe('completed')
    return job.result
  }
  expect((await command('open', { path: filename })).design.id).toBeTruthy()
  await expect.poll(() => page.evaluate(() => window.__nadocTest?.getDesignRenderer?.()?.getBackboneEntries?.().length ?? 0)).toBeGreaterThan(0)
  await framePart()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(20).length)).toBeGreaterThan(0)
  const before = await command('inspect')
  const capture = await command('capture', { durationMs: 1000, variant: 'B' })
  expect(capture.metrics.valid).toBe(true)
  expect(capture.after.controls_enabled).toBe(before.controls_enabled)
  for (let axis = 0; axis < 3; axis++) expect(capture.after.camera.position[axis]).toBeCloseTo(before.camera.position[axis], 8)
  const snapshot = await command('snapshot')
  expect(snapshot.width).toBeGreaterThan(100)
  const colors = await page.evaluate(async png => {
    const image = new Image(); image.src = png; await image.decode()
    const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height
    const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0)
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data
    const colors = new Set()
    for (let index = 0; index < pixels.length; index += 4 * 13) colors.add(`${pixels[index]},${pixels[index + 1]},${pixels[index + 2]}`)
    return colors.size
  }, snapshot.png)
  expect(colors, 'Snapshot must contain rendered pixels, not a discarded/blank buffer').toBeGreaterThan(10)
  expect(errors).toEqual([])
})
