import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

test('retired preferences reset and both placement slots render the accepted geometry', async ({ page }) => {
  test.setTimeout(60_000)
  await page.addInitScript(() => localStorage.setItem('nadoc.newPositioning.v2', 'false'))
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.goto('/?doc=__e2e__placement_comparison')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  expect(await page.evaluate(async () => (await import('/src/ui/new_positioning.js')).isNewPositioningOn())).toBe(true)
  expect(await page.evaluate(() => localStorage.getItem('nadoc.newPositioning.v2'))).toBeNull()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.fill('#new-design-name', '__e2e__placement_comparison')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  const design = JSON.parse(readFileSync(path.resolve('../tests/fixtures/cpd_2hb_1xt.nadoc'), 'utf8'))
  design.metadata.name = '__e2e__placement_comparison'
  await page.evaluate(async content => {
    await window.__nadocTest.nanoparticles.importDesign(content)
    await window.__nadocTest.setRepresentation('ballstick')
  }, JSON.stringify(design))
  await expect.poll(() => page.evaluate(() => {
    let count = 0
    window.__nadocTest.getAtomisticRenderer().visitAtoms(() => count++)
    return count
  })).toBeGreaterThan(0)
  const capture = () => page.evaluate(async () => {
    const renderer = window.__nadocTest.getDesignRenderer()
    const entries = [...renderer.getBackboneEntries(), ...renderer.getSlabEntries(), ...renderer.getXoverBeadEntries()]
    const matrices = entries.map(e => {
      const m = e.instMesh.matrix.clone()
      e.instMesh.getMatrixAt(e.id, m)
      return m.toArray()
    })
    const extraSlabs = window.__nadocTest.scene.getObjectByName('xoverExtraSlabs')
    for (let i = 0; i < extraSlabs.count; i++) {
      const m = extraSlabs.matrix.clone()
      extraSlabs.getMatrixAt(i, m)
      matrices.push(m.toArray())
    }
    const atoms = []
    window.__nadocTest.getAtomisticRenderer().visitAtoms((a, p) => atoms.push([a.serial, ...p.toArray()]))
    atoms.sort((a, b) => a[0] - b[0])
    const { store } = await import('/src/state/store.js')
    return { matrices, atoms, products: store.getState().currentDesign.photoproduct_junctions }
  })
  const accepted = await capture()
  for (const on of [false, true]) {
    const geometry = page.waitForResponse(r => r.url().includes('/design/geometry?') && r.url().includes(`measured_positioning=${on}`))
    const atomistic = page.waitForResponse(r => r.url().includes('/design/atomistic?') && r.url().includes(`measured_positioning=${on}`))
    await page.locator('#menu-item-debug').hover()
    await page.locator('#menu-help-new-positioning').click()
    expect((await geometry).ok()).toBe(true)
    expect((await atomistic).ok()).toBe(true)
    await expect.poll(capture).toEqual(accepted)
    expect(await page.evaluate(async () => (await import('/src/ui/new_positioning.js')).isNewPositioningOn())).toBe(on)
  }
})
