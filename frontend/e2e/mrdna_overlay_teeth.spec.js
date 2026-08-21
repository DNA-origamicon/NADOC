import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const TEETH = readFileSync(fileURLToPath(new URL('../../workspace/teeth.nadoc', import.meta.url)), 'utf8')

test('teeth saved poses preserve mrDNA bead and rod geometry across X sides', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.stack || error.message))

  await page.goto('/?doc=e2e-mrdna-overlay-teeth')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
  }, TEETH)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getDesignCameraPoseCount())).toBe(2)

  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({
    count: 4,
    representations: ['mrdna-coarse', 'mrdna-fine', 'hull-prism', 'full'],
    opacities: [0.7, 0.7, 0.45, 0.45],
    separation: 0.2,
  }))

  const poses = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.camera_poses)
  const captures = []
  for (let i = 0; i < poses.length; i++) {
    await page.evaluate(pose => window.__nadocTest.applyCameraPoseForTest(pose), poses[i])
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const image = await page.locator('#canvas').screenshot()
    await testInfo.attach(`teeth-${poses[i].name}.png`, { body: image, contentType: 'image/png' })
    captures.push(await page.evaluate(() => ({
      order: window.__nadocTest.multiOverlayRenderOrder(),
      geometry: window.__nadocTest.multiOverlayDiagnostics(),
    })))
  }

  expect(captures[0].order).not.toEqual(captures[1].order)
  expect(captures[0].geometry).toEqual(captures[1].geometry)
  const coarse = captures[0].geometry.find(layer => layer.representation === 'mrdna-coarse')
  const fine = captures[0].geometry.find(layer => layer.representation === 'mrdna-fine')
  expect(coarse.minBeadRadius).toBeCloseTo(0.55, 5)
  expect(coarse.maxBeadRadius).toBeCloseTo(0.55, 5)
  expect(fine.minBeadRadius).toBeCloseTo(0.28, 5)
  expect(fine.maxBeadRadius).toBeCloseTo(0.28, 5)
  for (const layer of [coarse, fine]) {
    expect(layer.minRodRadius).toBeCloseTo(0.13, 5)
    expect(layer.maxRodRadius).toBeCloseTo(0.13, 5)
  }
  expect(coarse.beadCount).toBeGreaterThan(0)
  expect(coarse.rodCount).toBeGreaterThan(0)
  expect(fine.beadCount).toBeGreaterThan(0)
  expect(fine.rodCount).toBeGreaterThan(0)
  expect(pageErrors).toEqual([])
})
