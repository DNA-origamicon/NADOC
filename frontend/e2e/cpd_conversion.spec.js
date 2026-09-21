import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

test.setTimeout(90_000)

// In-memory __e2e__ document; the standard teardown removes incidental saves.
test('converts an extra thymine pair through the context menu and moves it as a unit', async ({ page }) => {
  await page.setViewportSize({ width: 1800, height: 1100 })
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.goto('/?doc=__e2e__cpd_conversion')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.fill('#new-design-name', '__e2e__cpd_conversion')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  const design = JSON.parse(readFileSync(path.resolve('../tests/fixtures/cpd_extra_pair.nadoc'), 'utf8'))
  design.metadata.name = '__e2e__cpd_conversion'
  await page.evaluate(async content => {
    await window.__nadocTest.nanoparticles.importDesign(content)
    const { store } = await import('/src/state/store.js')
    const items = [0, 1].map(k => ({ kind: 'base', key: `__xb__:xo_direct:${k}` }))
    store.setState({ selection: { items, primary: items[0] } })
  }, JSON.stringify(design))
  const canvas = page.locator('#canvas')
  await canvas.click({ button: 'right', position: { x: 300, y: 200 } })
  await page.getByText('Convert to CPD…', { exact: true }).click()
  await expect(page.getByRole('button', { name: 'Convert to CPD', exact: true })).toBeEnabled()
  await expect(page.locator('svg[aria-label="3D CPD template preview"] circle')).not.toHaveCount(0)
  await page.getByRole('button', { name: 'Convert to CPD', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Convert to CPD', exact: true })).not.toBeVisible({ timeout: 30_000 })
  const result = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const { transformTargetsForSelection } = await import('/src/scene/nucleotide_transform_tool.js')
    const current = store.getState()
    return {
      products: current.currentDesign.photoproduct_junctions.length,
      poses: current.currentDesign.nucleotide_transforms.length,
      baseTargets: transformTargetsForSelection(current, { kind: 'base', key: '__xb__:xo_direct:0' }).length,
      crossoverTargets: transformTargetsForSelection(current, { kind: 'crossover', id: 'xo_direct' }).length,
    }
  })
  expect(result).toEqual({ products: 1, poses: 2, baseTargets: 2, crossoverTargets: 2 })
  await page.evaluate(async () => { await window.__nadocTest.setRepresentation('full') })
  await expect.poll(() => page.evaluate(() => {
    const bars = window.__nadocTest.getDesignRenderer().getHelixCtrl().root.getObjectByName('cpdSlabBonds')
    return bars?.visible ? bars.count : 0
  })).toBe(2)
  await expect(page.locator('#properties-content')).toContainText('Local bond relaxation')
  await page.evaluate(async () => { await window.__nadocTest.setRepresentation('ballstick') })
  await expect.poll(() => page.evaluate(() => !!window.__nadocTest.getAtomisticRenderer().residueInfo({ helix_id: '__xb__', crossover_id: 'xo_direct', k: 0 }))).toBe(true)
  for (const ref of [{ kind: 'base', key: '__xb__:xo_direct:0' }, { kind: 'crossover', id: 'xo_direct', subtype: 'crossover' }]) {
    await page.evaluate(async item => {
      const { store } = await import('/src/state/store.js')
      store.setState({ selection: { items: [item], primary: item } })
    }, ref)
    await page.keyboard.press('m')
    await expect.poll(() => page.evaluate(() => window.__nadocTest.getNucleotideTransformScreenState().active)).toBe(true)
    await page.keyboard.press('Escape')
    await expect.poll(() => page.evaluate(() => window.__nadocTest.getNucleotideTransformScreenState().active)).toBe(false)
  }
  expect(errors).toEqual([])
})

test('saved 2hb CPD has only slab crosslinks and can re-relax nearby clashes', async ({ page }) => {
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.setViewportSize({ width: 1800, height: 1100 })
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.goto('/?doc=__e2e__cpd_2hb_steric')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.fill('#new-design-name', '__e2e__cpd_2hb_steric')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  const design = JSON.parse(readFileSync(path.resolve('../tests/fixtures/cpd_2hb_1xt.nadoc'), 'utf8'))
  design.metadata.name = '__e2e__cpd_2hb_steric'
  await page.evaluate(async content => {
    await window.__nadocTest.nanoparticles.importDesign(content)
    await window.__nadocTest.setRepresentation('full')
    const { store } = await import('/src/state/store.js')
    const key = store.getState().currentDesign.photoproduct_junctions[0].base_key_1
    const ref = { kind: 'base', key }
    store.setState({ selection: { items: [ref], primary: ref } })
  }, JSON.stringify(design))
  const barCounts = () => page.evaluate(() => {
    const scene = window.__nadocTest.scene
    const bars = scene.getObjectByName('cpdSlabBonds')
    const legacy = scene.getObjectByName('formedPhotoproductOverlay')
    return { slabs: bars?.visible ? bars.count : 0, backbone: legacy?.children.reduce((n, pair) => n + pair.children.length, 0) ?? 0 }
  })
  await expect.poll(barCounts).toEqual({ slabs: 2, backbone: 0 })
  await page.getByRole('button', { name: 'Relax CPD bonds and clashes' }).click()
  await expect(page.locator('#properties-content')).toContainText('severe clashes: 20 → 0', { timeout: 30_000 })
  await expect.poll(barCounts).toEqual({ slabs: 2, backbone: 0 })
  expect(errors).toEqual([])
})

test('fresh 2hb conversion matches subsequent relaxation in Full representation', async ({ page }) => {
  await page.setViewportSize({ width: 1800, height: 1100 })
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.goto('/?doc=__e2e__cpd_2hb_fresh')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.fill('#new-design-name', '__e2e__cpd_2hb_fresh')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  const design = JSON.parse(readFileSync(path.resolve('../tests/fixtures/cpd_2hb_1xt.nadoc'), 'utf8'))
  const lesion = design.photoproduct_junctions[0]
  const keys = [lesion.base_key_1, lesion.base_key_2]
  design.photoproduct_junctions = []
  design.nucleotide_transforms = []
  design.metadata.name = '__e2e__cpd_2hb_fresh'
  await page.evaluate(async ({ content, keys }) => {
    await window.__nadocTest.nanoparticles.importDesign(content)
    await window.__nadocTest.setRepresentation('full')
    const { store } = await import('/src/state/store.js')
    const items = keys.map(key => ({ kind: 'base', key }))
    store.setState({ selection: { items, primary: items[0] } })
  }, { content: JSON.stringify(design), keys })
  await page.locator('#canvas').click({ button: 'right', position: { x: 300, y: 200 } })
  await page.getByText('Convert to CPD…', { exact: true }).click()
  await page.getByRole('button', { name: 'Convert to CPD', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Convert to CPD', exact: true })).not.toBeVisible({ timeout: 30_000 })
  const snapshot = () => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const design = store.getState().currentDesign
    return {
      poses: design.nucleotide_transforms.map(t => [...t.translation, ...t.rotation]).flat(),
      report: design.photoproduct_junctions[0].bond_relaxation,
      bars: window.__nadocTest.scene.getObjectByName('cpdSlabBonds')?.count,
    }
  })
  const fresh = await snapshot()
  expect(fresh.report.clashes_after.count).toBe(0)
  expect(fresh.report.rms_error_after_nm).toBeLessThan(0.20)
  expect(fresh.bars).toBe(2)
  await page.getByRole('button', { name: 'Relax CPD bonds and clashes' }).click()
  await expect(page.getByRole('button', { name: 'Relax CPD bonds and clashes' })).toBeEnabled({ timeout: 30_000 })
  const relaxed = await snapshot()
  expect(relaxed.report.clashes_before.count).toBe(0)
  expect(relaxed.report.clashes_after.count).toBe(0)
  expect(relaxed.bars).toBe(2)
  expect(relaxed.poses.length).toBe(fresh.poses.length)
  relaxed.poses.forEach((value, index) => expect(value).toBeCloseTo(fresh.poses[index], 7))
})
