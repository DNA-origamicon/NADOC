import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const FIXTURE = resolve(process.cwd(), '..', 'workspace', 'bench_fixtures', 'bench_hinge_020.nass')
test.skip(!existsSync(FIXTURE), `fixture missing: ${FIXTURE}`)

test('assembly cylinders render a real photomode key-shadow map', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = []
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', error => errors.push(String(error)))

  await page.goto('/?doc=__e2e__assembly-photo-shadow&open=bench_fixtures%2Fbench_hinge_020.nass&open-type=assembly')
  await page.waitForFunction(() => {
    const state = window.__NADOC_DBG__?.store.getState()
    return state?.assemblyActive && state.currentAssembly?.instances?.length === 20
  }, null, { timeout: 45_000 })

  await page.locator('#photo-tab-btn').click()
  await page.locator('#photo-studio-environment').uncheck()
  // A smaller map keeps the software-WebGL regression fast while exercising
  // exactly the same custom depth shaders and shadow-camera path.
  await page.locator('#photo-key-shadow-mapsize').selectOption('1024')
  await page.waitForFunction(() => {
    const d = window.__photoMode?.getDiagnostics?.()
    return d?.active
      && d.bounds?.radius > 0
      && d.keyLight?.castShadow
      && d.keyLight?.mapRendered
      && d.meshes?.casters > 0
      && d.meshes?.receivers > 0
  }, null, { timeout: 90_000 })

  const diagnostics = await page.evaluate(() => window.__photoMode.getDiagnostics())
  expect(diagnostics.keyLight.mapSize).toBe(1024)
  expect(diagnostics.shadowCastingLights).toHaveLength(1)
  expect(diagnostics.shadowCastingLights[0].isKey).toBe(true)
  expect(diagnostics.studioEnvironment).toMatchObject({ enabled: false, bound: false })
  expect(diagnostics.figureEffects).toMatchObject({ outline: false, depthCue: false, passEnabled: false })
  expect(diagnostics.bounds.radius).toBeLessThan(1000)
  expect(diagnostics.bounds.largest?.[0]?.extent ?? 0).toBeLessThan(1000)
  expect(diagnostics.shadowGeometry.targetCenterError).toBeLessThan(1e-4)
  expect(diagnostics.shadowGeometry.shadowCameraAlignment).toBeGreaterThan(0.9999)
  expect(diagnostics.shadowGeometry.outsideCorners).toBe(0)
  expect(diagnostics.meshes.casters).toBeGreaterThan(0)
  expect(diagnostics.meshes.receivers).toBeGreaterThan(0)
  expect(errors.filter(error => /shader|glsl|WebGLProgram/i.test(error))).toEqual([])
})
