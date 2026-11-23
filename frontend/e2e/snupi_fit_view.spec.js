import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Display-only transport fixtures: no authored/imported structures, saves, jobs,
// screenshots or downloads. Session persistence is disabled by the e2e backend.
// The configured global teardown removes the isolated Vite bridge credentials;
// the cleanup reporter removes Playwright output even on failure.
function frame(kind, index = 0) {
  const positions = [100 + index * 300, -40, 10, 300 + index * 300, 80, 90]
  const header = Buffer.from(JSON.stringify({ kind, count: 2, min: 0, max: 1,
    identities: false, joints: 0, frames: 2, frame: index }))
  const offset = Math.ceil((12 + header.length) / 4) * 4
  const out = Buffer.alloc(offset + 32)
  ;[0x5A495643, 1, header.length].forEach((v, i) => out.writeUInt32LE(v, 4 * i))
  header.copy(out, 12)
  ;[...positions, 0, 1].forEach((v, i) => out.writeFloatLE(v, offset + i * 4))
  return out
}

test('F fits every SNUPI result mode and the current trajectory frame in both hosts', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await page.route('**/api/snupi/jobs/__e2e__fit**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('visualization-bin')) return route.fulfill({ body: frame(url.searchParams.get('mode')), contentType: 'application/octet-stream' })
    if (url.pathname.endsWith('trajectory-frame-bin')) return route.fulfill({ body: frame('deform', Number(url.searchParams.get('frame'))), contentType: 'application/octet-stream' })
    return route.fulfill({ json: { job_id: '__e2e__fit', status: 'completed', n_nucleotides: 2 } })
  })
  await page.goto('/?doc=__e2e__snupi_fit')
  await page.waitForFunction(() => !!window.__nadocTest?.snupiDisplay)
  await page.evaluate(() => document.getElementById('welcome-screen')?.classList.add('hidden'))
  for (const assemblyActive of [false, true]) {
    await page.evaluate(value => window.__nadocTest.store.setState({ assemblyActive: value }), assemblyActive)
    for (const mode of ['showCandoStyle', 'showDeform', 'showFlex', 'showDeviation', 'showTrajectory']) {
      expect(await page.evaluate(async method => (await window.__nadocTest.snupiDisplay[method]('__e2e__fit', null, { autoplay: false })).ok, mode)).toBe(true)
      for (const width of [1200, 650]) {
        await page.setViewportSize({ width, height: 850 })
        await page.evaluate(() => {
          const { camera, controls } = window.__nadocTest
          controls.target.set(-200, -200, -200); camera.position.set(-199, -199, -199); controls.update()
          document.activeElement?.blur()
        })
        await page.keyboard.press('f')
        const check = await page.evaluate(() => {
          const { camera, controls, snupiDisplay } = window.__nadocTest
          const box = snupiDisplay.getBoundingBox(), p = camera.position.clone()
          camera.updateMatrixWorld()
          let max = 0
          for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
            p.set(x, y, z).project(camera); max = Math.max(max, Math.abs(p.x), Math.abs(p.y))
          }
          return { max, centerError: controls.target.distanceTo(box.getCenter(p)) }
        })
        expect(check.centerError).toBeLessThan(1e-6)
        expect(check.max).toBeLessThan(1)
      }
      if (mode === 'showTrajectory') {
        await page.evaluate(() => window.__nadocTest.snupiDisplay.seekFullTrajectoryFrame(1))
        await page.keyboard.press('F')
        expect(await page.evaluate(() => window.__nadocTest.controls.target.x)).toBeCloseTo(500)
      }
    }
    await page.evaluate(() => window.__nadocTest.snupiDisplay.stopAndRestore())
  }
  expect(errors).toEqual([])
})
