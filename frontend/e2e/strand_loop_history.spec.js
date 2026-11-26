import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Only isolated smoke servers. __e2e__ parts and project stores are removed by global teardown.
test('loop history edits, scrubs, reverts, deletes and restores through undo/redo', async ({ page }, testInfo) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  const doc = '__e2e__strand_loop_history'
  await loadScaffoldedPart(page, { doc, name: 'strand_loop_history' })
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const s = window.__nadocTest.store.getState().currentDesign.strands.find(s => s.strand_type === 'scaffold')
    const d = s.domains[0]
    await api.setStrandLoop({ strand_id: s.id, helix_id: d.helix_id, bp_index: 30,
      direction: d.direction, length: 6, aspect_ratio: 3, rotation_deg: 0 })
  })
  const count = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.strands
    .reduce((sum, s) => sum + (s.loops || []).reduce((n, l) => n + l.length, 0), 0))
  await expect.poll(count).toBe(6)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.saveDesignToWorkspace('__e2e__strand_loop_history.nadoc')
  })
  await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  const expand = async () => {
    const button = page.getByTitle('Expand Fine Routing', { exact: true }).last()
    if (await button.count()) await button.click()
  }
  await expand()
  await page.getByRole('button', { name: '✎' }).and(page.locator('[title$=" inputs"]')).last().click()
  const modal = page.getByRole('dialog', { name: 'Edit loop', exact: true })
  await expect(modal).toBeVisible()
  await modal.getByLabel('Loop bases', { exact: true }).fill('12')
  await modal.getByLabel('Aspect ratio', { exact: true }).fill('2')
  await page.screenshot({ path: testInfo.outputPath('loop-history-editor.png') })
  await modal.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(modal).toBeHidden()
  await expect.poll(count).toBe(12)
  await page.keyboard.press('Control+z')
  await expect.poll(count).toBe(6)
  await page.keyboard.press('Control+Shift+z')
  await expect.poll(count).toBe(12)
  // Use the same client navigation as the timeline; verify rendered loop beads too.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const log = window.__nadocTest.store.getState().currentDesign.feature_log
    await api.seekFeatures(log.length - 1, -2)
  })
  await expect.poll(count).toBe(0)
  await page.evaluate(async () => (await import('/src/api/client.js')).seekFeatures(-1))
  await expect.poll(count).toBe(12)
  for (const action of ['Revert', 'Delete']) {
    await expand()
    const title = action === 'Revert' ? /^Revert to before sub-step/ : /^Delete sub-step/
    await page.getByTitle(title).last().click()
    await page.getByRole('button', { name: action, exact: true }).click()
    await expect.poll(count).toBe(0)
    await page.keyboard.press('Control+z')
    await expect.poll(count).toBe(12)
    await page.keyboard.press('Control+Shift+z')
    await expect.poll(count).toBe(0)
    await page.keyboard.press('Control+z')
    await expect.poll(count).toBe(12)
  }
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getDesignRenderer()
    .getBackboneEntries().filter(e => e.nuc.loop_order > 0).length)).toBe(12)
  expect(errors).toEqual([])
})
