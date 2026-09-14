import { expect, test } from '@playwright/test'

test('gold quenching uses live poses and distinguishes estimates from unknown QDs', async ({ page }) => {
  test.setTimeout(120_000)
  await page.route(/\/api\/(md|oxdna)\//, route => route.abort())
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__gold_quenching')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  const gold = await page.evaluate(() => window.__nadocTest.nanoparticles.create(3))
  await page.evaluate(() => window.__nadocTest.nanoparticles.createQuantumDot('nn-hecz-520', 9))
  // A deterministic point-donor fixture isolates photophysics from DNA building.
  // Gold and QD import, gizmo movement, glow rendering and UI are the real app.
  await page.evaluate(async () => {
    const { Vector3 } = await import('/node_modules/three/build/three.module.js')
    const renderer = window.__nadocTest.getDesignRenderer()
    renderer.getFluoroEntries = () => [{ nuc: { modification: 'fam' }, pos: new Vector3(12.12, 0, 0) }]
    const original = renderer.setFluorescenceGlow.bind(renderer)
    renderer.setFluorescenceGlow = entries => { window.__goldTestBrightness = entries[0]?.brightness; original(entries) }
    document.getElementById('menu-view-fluorescence').click()
    document.getElementById('menu-view-fret').click()
  })
  await expect.poll(() => page.evaluate(() => window.__goldTestBrightness)).toBeCloseTo(0.5)
  await expect(page.locator('#gold-quenching-status')).toContainText('1 estimated · 1 uncalibrated')
  await page.click('#gold-quenching-status')
  const dialog = page.getByRole('dialog', { name: 'Gold quenching estimates' })
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('tbody tr').filter({ hasText: 'fam' })).toContainText('50.00%')
  await expect(dialog.locator('tbody tr').filter({ hasText: 'Unknown' })).toHaveCount(1)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await page.evaluate(id => {
    window.__nadocTest.nanoparticles.select(id)
    window.__nadocTest.nanoparticles.gizmoSetTransform([-10.62, 0, 0], [0, 0, 0, 1])
  }, gold.nanoparticle_id)
  await expect.poll(() => page.evaluate(() => window.__goldTestBrightness)).toBeCloseTo(16 / 17)
  await page.click('#mr-cancel-btn')
  await expect.poll(() => page.evaluate(() => window.__goldTestBrightness)).toBeCloseTo(0.5)
  await page.evaluate(() => document.getElementById('menu-view-fret').click())
  await expect.poll(() => page.evaluate(() => window.__goldTestBrightness)).toBe(1)
  await expect(page.locator('#gold-quenching-status')).toBeHidden()
  const dots = await page.evaluate(() => window.__nadocTest.nanoparticles.rendered().filter(p => p.kind === 'quantum_dot'))
  expect(dots[0].emissiveIntensity).toBe(1.5)
})
