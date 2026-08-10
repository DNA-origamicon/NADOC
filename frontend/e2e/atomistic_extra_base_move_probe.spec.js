import { test, expect } from '@playwright/test'
import { copyFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SOURCE = fileURLToPath(new URL('../../workspace/2hb_1xT.nadoc', import.meta.url))
const WORKSPACE = path.dirname(SOURCE)
// The library intentionally hides internal-looking `__*` files, so keep the
// disposable fixture visible while the welcome-screen opener is under test.
const STEM = 'e2eatomisticxmoveprobe'
const TEMP_FILE = path.join(WORKSPACE, `${STEM}.nadoc`)

const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]))

test.beforeAll(() => copyFileSync(SOURCE, TEMP_FILE))
test.afterAll(() => rmSync(TEMP_FILE, { force: true }))

test('atomistic extra-base Apply does not enter a loading/position loop', async ({ page }) => {
  test.setTimeout(240_000)
  await page.goto('/?doc=e2e-atomistic-extra-base-move-probe')
  await page.waitForSelector('#canvas')
  const workspaceSaves = []
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/design/save-workspace')) {
      workspaceSaves.push(performance.now())
    }
  })
  const welcome = page.locator('#welcome-screen')
  await welcome.locator('.lib-row-name', { hasText: new RegExp(`^${STEM}$`) })
    .first().click({ timeout: 60_000 })
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })

  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getBaseCandidates().filter(candidate => candidate.family === 'xover').length,
  )).toBeGreaterThan(0)
  const selectedKey = await page.evaluate(() => window.__nadocTest.getBaseCandidates()
    .find(item => item.family === 'xover').key)
  await page.evaluate(() => document.getElementById('menu-view-atomistic-ballstick')?.click())
  await expect.poll(() => page.evaluate(() => {
    const rendered = window.__nadocTest.getRenderedXoverExtraGeometry()
    return Object.values(rendered).reduce((sum, extra) => sum + extra.atoms.length, 0)
  }), { timeout: 90_000 }).toBeGreaterThan(0)
  await expect(page.locator('.toast-message', { hasText: 'Loading atomistic model…' }))
    .toHaveCount(0, { timeout: 10_000 })

  await page.evaluate(async candidateKey => {
    window.__atomMoveTarget = candidateKey.slice('__xb__:'.length)
    window.__nadocTest.store.setState({ multiSelectedBaseKeys: [candidateKey] })

    const centroid = () => {
      const extra = window.__nadocTest.getRenderedXoverExtraGeometry()[window.__atomMoveTarget]
      if (!extra?.atoms?.length) return null
      const sum = extra.atoms.reduce((acc, atom) => acc.map((v, i) => v + atom.pos[i]), [0, 0, 0])
      return sum.map(v => v / extra.atoms.length)
    }
    const { installAtomisticLoadingProbe } = await import(
      '/src/scene/debug/atomistic_loading_probe.js'
    )
    window.__atomLoadingProbe = installAtomisticLoadingProbe({
      snapshot: () => ({ target: window.__atomMoveTarget, atomCentroid: centroid() }),
    })
    window.__atomMoveSamples = []
    window.__atomMoveSampleTimer = setInterval(() => {
      window.__atomMoveSamples.push({
        atMs: performance.now(),
        atomCentroid: centroid(),
        loadingPings: window.__atomLoadingProbe.count(),
      })
    }, 25)
  }, selectedKey)

  const before = await page.evaluate(() => {
    const extra = window.__nadocTest.getRenderedXoverExtraGeometry()[window.__atomMoveTarget]
    if (!extra?.atoms?.length) return null
    const sum = extra.atoms.reduce((acc, atom) => acc.map((v, i) => v + atom.pos[i]), [0, 0, 0])
    return sum.map(v => v / extra.atoms.length)
  })
  expect(before).not.toBeNull()

  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('m')
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getNucleotideTransformScreenState().active)).toBe(true)
  const gizmo = await page.evaluate(() => window.__nadocTest.getNucleotideTransformScreenState())

  await page.mouse.move(gizmo.screenPivot.x, gizmo.screenPivot.y)
  await page.mouse.down()
  await page.mouse.move(gizmo.screenPivot.x + 80, gizmo.screenPivot.y - 35, { steps: 12 })
  await page.mouse.up()
  await page.waitForTimeout(150)

  const preview = await page.evaluate(() => {
    const extra = window.__nadocTest.getRenderedXoverExtraGeometry()[window.__atomMoveTarget]
    const sum = extra.atoms.reduce((acc, atom) => acc.map((v, i) => v + atom.pos[i]), [0, 0, 0])
    return sum.map(v => v / extra.atoms.length)
  })
  expect(distance(before, preview), 'TransformControls must actually move the extra base')
    .toBeGreaterThan(0.05)

  // Exercise the real panel Apply path. It detaches the optimistic preview,
  // persists the extra_base transform, and lets the design subscriber own the
  // one atomistic rebuild.
  await page.evaluate(() => { window.__atomMoveSamples = [] })
  const saveRequestStart = workspaceSaves.length
  await page.evaluate(() => document.getElementById('mr-apply-btn')?.click())
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getNucleotideTransformScreenState().active)).toBe(false)
  await expect.poll(() => page.evaluate(() => window.__atomLoadingProbe.count()), {
    timeout: 30_000,
    message: 'the committed design never started its expected atomistic rebuild',
  }).toBeGreaterThan(0)
  await expect(page.locator('.toast-message', { hasText: 'Loading atomistic model…' }))
    .toHaveCount(0, { timeout: 90_000 })

  // The reported failure was a continuing loop, so observe well beyond the
  // first rebuild instead of declaring success as soon as its toast closes.
  await page.waitForTimeout(5_500)
  const diagnostic = await page.evaluate(() => {
    clearInterval(window.__atomMoveSampleTimer)
    const events = window.__atomLoadingProbe.events()
    window.__atomLoadingProbe.stop()
    const samples = window.__atomMoveSamples
    const extra = window.__nadocTest.getRenderedXoverExtraGeometry()[window.__atomMoveTarget]
    const sum = extra.atoms.reduce((acc, atom) => acc.map((v, i) => v + atom.pos[i]), [0, 0, 0])
    return {
      events,
      samples,
      final: sum.map(v => v / extra.atoms.length),
    }
  })

  const movedDistance = distance(before, preview)
  const oldPositionSamples = diagnostic.samples.filter(sample => sample.atomCentroid &&
    distance(sample.atomCentroid, before) < movedDistance * 0.2)
  const movedPositionSamples = diagnostic.samples.filter(sample => sample.atomCentroid &&
    distance(sample.atomCentroid, preview) < movedDistance * 0.2)
  const report = {
    selectedKey,
    before,
    preview,
    final: diagnostic.final,
    movedDistance,
    loadingPingCount: diagnostic.events.length,
    loadingPings: diagnostic.events,
    sampleCount: diagnostic.samples.length,
    oldPositionSampleCount: oldPositionSamples.length,
    movedPositionSampleCount: movedPositionSamples.length,
    workspaceSaveCountAfterApply: workspaceSaves.length - saveRequestStart,
  }
  console.log('ATOMISTIC_EXTRA_BASE_MOVE_PROBE=' + JSON.stringify(report))

  expect(diagnostic.events, JSON.stringify(report)).toHaveLength(1)
  expect(oldPositionSamples, JSON.stringify(report)).toHaveLength(0)
  expect(movedPositionSamples.length, JSON.stringify(report)).toBeGreaterThan(0)
  expect(distance(diagnostic.final, preview), JSON.stringify(report)).toBeLessThan(2e-3)
  expect(report.workspaceSaveCountAfterApply, JSON.stringify(report)).toBe(1)
})
