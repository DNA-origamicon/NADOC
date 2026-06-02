/**
 * Regression: a belt rider must NOT flicker between its new and original
 * position while a pulley is rotated manually. The bug was the ticker driving
 * riders every frame from a stale `_shadow` angle, fighting the store-driven
 * subscription. Fix: the ticker only drives riders during RPM spin.
 *
 * Uses workspace/Belt_test1.nass (1 belt + 1 rider with ride-state).
 * Run: cd frontend && npx playwright test e2e/belt_rider_flicker.spec.js \
 *        --config playwright.bench.config.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIXTURE = resolvePath(process.cwd(), '..', 'workspace', 'Belt_test1.nass')
test.setTimeout(120_000)
test.skip(!existsSync(FIXTURE), `fixture missing: ${FIXTURE}`)

test('belt rider does not flicker on manual pulley rotation', async ({ page }) => {
  page.on('pageerror', e => console.log('[pageerror] ' + e.message))
  await page.goto('http://localhost:5173/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.store, null, { timeout: 30_000 })

  const nass = readFileSync(FIXTURE, 'utf-8')
  await page.evaluate(async (content) => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(content)
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  }, nass)
  await page.waitForFunction(
    () => (window.__NADOC_DBG__.store.getState().currentAssembly?.belt_riders?.length ?? 0) >= 1,
    null, { timeout: 30_000 })
  await page.waitForTimeout(3000) // render + let the ticker populate _shadow via coupling

  const ids = await page.evaluate(() => {
    const a = window.__NADOC_DBG__.store.getState().currentAssembly
    const r = a.belt_riders[0]
    const belt = a.belt_paths.find(b => b.id === r.belt_path_id)
    return { instId: r.instance_id, jointA: belt.pulley_a.joint_id, ref: r.ref_angle ?? 0 }
  })
  const posOf = () => page.evaluate((instId) => {
    const D = window.__NADOC_DBG__
    const m = D.assemblyRenderer.getLiveTransform(instId)
    return m ? new D.THREE.Vector3().setFromMatrixPosition(m).toArray() : null
  }, ids.instId)
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])

  const orig = await posOf()
  expect(orig).not.toBe(null)

  // Rotate the pulley a meaningful amount (discrete PATCH, the manual-rotation path).
  await page.evaluate(async (d) => {
    const api = await import('/src/api/client.js')
    await api.patchAssemblyJoint(d.jointA, { current_value: d.ref + 1.2 })
  }, ids)

  // Sample the rider position repeatedly over ~1.2 s (covers the old ~1s stale-
  // _shadow window). With the bug it oscillates back toward `orig`; fixed, it
  // holds the moved position.
  const samples = []
  for (let i = 0; i < 8; i++) { samples.push(await posOf()); await page.waitForTimeout(150) }

  const moved = samples.map(s => dist(s, orig))
  const minMoved = Math.min(...moved)
  const maxMoved = Math.max(...moved)
  console.log('moved-from-orig over time:', moved.map(v => +v.toFixed(2)))
  // It actually moved...
  expect(maxMoved).toBeGreaterThan(0.5)
  // ...and never snapped back toward the original (no flicker): the closest any
  // sample got to `orig` is still clearly "moved", and the spread is tiny.
  expect(minMoved).toBeGreaterThan(0.5)
  expect(maxMoved - minMoved).toBeLessThan(0.1)
})
