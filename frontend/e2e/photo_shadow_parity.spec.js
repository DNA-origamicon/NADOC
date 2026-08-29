import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const PART = resolve(process.cwd(), '..', 'workspace', 'Ultimate Polymer Hinge.nadoc')
const ASSEMBLY = resolve(process.cwd(), '..', 'workspace', 'bench_fixtures', 'bench_hinge_001.nass')
test.skip(!existsSync(PART) || !existsSync(ASSEMBLY), 'hinge parity fixtures are missing')

async function loadPhoto(page, kind) {
  const open = kind === 'assembly'
    ? 'bench_fixtures%2Fbench_hinge_001.nass'
    : 'Ultimate%20Polymer%20Hinge.nadoc'
  await page.goto(`/?doc=__e2e__photo-shadow-${kind}&open=${open}&open-type=${kind === 'assembly' ? 'assembly' : 'design'}`)
  await page.waitForFunction(expected => {
    const state = window.__NADOC_DBG__?.store.getState()
    return expected === 'assembly'
      ? state?.assemblyActive && state.currentAssembly?.instances?.length === 1
      : !state?.assemblyActive && (state?.currentGeometry?.length ?? 0) > 0
  }, kind, { timeout: 45_000 })
  if (kind === 'design') {
    await page.evaluate(async () => window.__nadocTest?.setRepresentation?.('cylinders'))
    await page.waitForTimeout(500)
  }
  await page.locator('#photo-tab-btn').click()
  await page.locator('#photo-key-shadow-mapsize').selectOption('1024')
  await page.waitForFunction(() => {
    const d = window.__photoMode?.getDiagnostics?.()
    return d?.keyLight?.mapRendered && d?.shadowGeometry && d.meshes?.casters > 0
  }, null, { timeout: 90_000 })
}

async function rotateCamera(page) {
  await page.evaluate(() => {
    const { camera, controls } = window.__NADOC_DBG__
    const distance = camera.position.distanceTo(controls.target)
    camera.position.copy(controls.target).add({ x: distance * 0.8, y: distance * 0.35, z: distance * 0.48 })
    camera.lookAt(controls.target)
    controls.update()
  })
  await page.waitForTimeout(250)
}

test('part and one-instance assembly have camera-pinned, fitted shadow rigs', async ({ page }, testInfo) => {
  test.setTimeout(300_000)
  const snapshots = {}
  for (const kind of ['design', 'assembly']) {
    await loadPhoto(page, kind)
    const before = await page.evaluate(() => window.__photoMode.getDiagnostics())
    await rotateCamera(page)
    const after = await page.evaluate(() => window.__photoMode.getDiagnostics())
    snapshots[kind] = { before, after }

    expect(before.shadowGeometry.targetCenterError).toBeLessThan(1e-4)
    expect(before.shadowGeometry.shadowCameraAlignment).toBeGreaterThan(0.9999)
    expect(before.shadowGeometry.outsideCorners).toBe(0)
    expect(after.rigMatchesCamera).toBe(true)
    after.shadowGeometry.cameraRay.forEach((value, i) =>
      expect(value).toBeCloseTo(before.shadowGeometry.cameraRay[i], 4))
    expect(after.shadowGeometry.outsideCorners).toBe(0)
  }

  await testInfo.attach('shadow-parity.json', {
    body: JSON.stringify(snapshots, null, 2), contentType: 'application/json',
  })
  const ratio = snapshots.assembly.before.bounds.radius / snapshots.design.before.bounds.radius
  expect(ratio).toBeGreaterThan(0.8)
  expect(ratio).toBeLessThan(1.25)
})
