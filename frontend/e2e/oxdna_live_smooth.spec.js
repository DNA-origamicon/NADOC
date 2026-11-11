import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'

const fixture = path.resolve(process.cwd(), '..', 'Examples', '2hb_xover_atoms_test.nadoc')
const hashFixture = async () => createHash('sha256').update(await readFile(fixture)).digest('hex')
let originalHash
test.beforeEach(async () => { originalHash = await hashFixture() })
test.afterEach(async () => { expect(await hashFixture()).toBe(originalHash) })

// Read-only existing fixture plus intercepted live frames, rendered through the
// real display adapter. No designs/jobs are authored or saved; session cache is
// disabled by the smoke config. Screenshots stay in Playwright output directories.
test('live popup blends arriving frames and stops cleanly', async ({ page }, testInfo) => {
  let burst = 0, baseline = []
  // Isolate this software jitter measurement from unrelated stored-job backfill.
  await page.route(/\/api\/(oxdna|namd|lammps|mrdna|snupi)\/jobs(?:\?.*)?$/, route => route.fulfill({ json: [] }))
  await page.route('**/api/oxdna/live/**', async route => {
    const url = route.request().url()
    const body = url.endsWith('/available') ? { available: true }
      : url.endsWith('/start') ? { session_id: 'test-live' }
        : url.endsWith('/frame') ? { ready: true, status: 'running', n_bursts: ++burst, n_positions: baseline.length,
          positions: baseline.map(p => ({ ...p, backbone_position: p.backbone_position.map((x, i) => x + (i === 0 ? burst * .3 : 0)) })) }
          : { ok: true }
    if (url.endsWith('/frame') && burst === 8) await new Promise(resolve => setTimeout(resolve, 900))
    return route.fulfill({ json: body })
  })
  await page.goto('/')
  await expect(page.locator('#canvas')).toBeVisible()
  baseline = await page.evaluate(async fixturePath => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(fixturePath)
    const positions = (await api.getGeometry()).nucleotides
    // API-only fixture loading does not perform File→Open's welcome/camera step.
    // Expose the read-only diagnostic model without changing its coordinates.
    document.getElementById('welcome-screen').classList.add('hidden')
    const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity]
    for (const p of positions) p.backbone_position.forEach((x, i) => { low[i] = Math.min(low[i], x); high[i] = Math.max(high[i], x) })
    const center = low.map((x, i) => (x + high[i]) / 2), radius = Math.max(...low.map((x, i) => high[i] - x))
    window.__nadocTest.applyCameraPoseForTest({ position: center.map((x, i) => x + radius * [1.5, .9, 1.5][i]), target: center, up: [0, 1, 0] })
    return positions
  }, fixture)
  expect(baseline.length).toBeGreaterThan(0)
  await page.evaluate(async origin => {
    const api = await import('/src/api/client.js')
    const { initOxdnaDisplay } = await import('/src/ui/oxdna_display.js')
    const display = initOxdnaDisplay({ designRenderer: window.__nadocTest.getDesignRenderer(), api })
    const { initOxdnaLive } = await import('/src/ui/oxdna_live_controller.js')
    const old = document.getElementById('oxdna-jobs-live-btn')
    old.removeAttribute('id')
    const button = document.createElement('button'); button.id = 'oxdna-jobs-live-btn'
    document.body.append(button)
    document.getElementById('oxdna-live-playback')?.remove()
    window.liveSamples = []
    window.liveTest = initOxdnaLive({ getSelectedJob: () => ({ job_id: 'test', status: 'completed' }),
      oxdnaDisplay: { displayLiveFrame: p => { display.displayLiveFrame(p); window.liveSamples.push(p[0].backbone_position[0] - origin) },
        mode: display.mode, stopAndRestore: display.stopAndRestore } })
    window.liveTest.toggle()
  }, baseline[0].backbone_position[0])
  const popup = page.locator('#oxdna-live-playback')
  await expect(popup).toBeVisible()
  const hostBox = await page.locator('#canvas-area').boundingBox(), box = await popup.boundingBox()
  expect(Math.abs(box.x - hostBox.x - 12)).toBeLessThan(2)
  expect(Math.abs(box.y - hostBox.y - 12)).toBeLessThan(2)
  await popup.getByLabel('Smooth', { exact: true }).check()
  await expect.poll(() => page.evaluate(() => window.liveSamples.some(x => Math.abs(x / .3 - Math.round(x / .3)) > .02))).toBe(true)
  await expect.poll(() => burst, { timeout: 15000 }).toBeGreaterThanOrEqual(11)
  expect(await page.evaluate(() => window.liveTest.getDiagnostics().underruns)).toBe(0)
  await popup.locator('summary').click()
  await expect(popup.locator('.live-timing')).toContainText('Buffer stalls: 0')
  await page.screenshot({ path: testInfo.outputPath('live-buffer.png') })
  await popup.getByLabel('Smooth', { exact: true }).uncheck()
  await page.evaluate(() => window.liveTest.stop())
  await expect(popup).toBeHidden()
  const count = await page.evaluate(() => window.liveSamples.length)
  await page.waitForTimeout(650)
  expect(await page.evaluate(() => window.liveSamples.length)).toBe(count)
})
