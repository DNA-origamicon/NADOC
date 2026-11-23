import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

// Inspect the existing design without committing a transform. Normal Open refreshes
// identity signoff metadata; every other saved field must remain unchanged. Session
// caching is disabled and the reporter removes screenshot/trace artifacts.
const source = process.env.NADOC_MOVE_CLEAR_FIXTURE || path.resolve(import.meta.dirname,
  '../../workspace/Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc')
const snapshot = () => {
  const data = JSON.parse(readFileSync(source, 'utf8'))
  delete data.metadata.identity_confirmed_at
  delete data.metadata.identity_last_known_path
  return data
}
test('JJ_Hinge: clear releases the Move/Rotate target and permits another cluster', async ({ page }) => {
  test.skip(!existsSync(source), 'JJ_Hinge fixture is not available on this checkout')
  test.setTimeout(120_000)
  const before = snapshot(), errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/?doc=__e2e__move-clear-jj&open=${encodeURIComponent(source)}&open-type=part`)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.cluster_transforms?.length > 1)
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  const ids = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign
    .cluster_transforms.filter(c => c.helix_ids?.length).map(c => c.id))
  expect(ids.length).toBeGreaterThan(1)
  const select = id => page.evaluate(async id => {
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'cluster', id }])
  }, id)
  await select(ids[0])
  await page.keyboard.press('m')
  const popup = page.locator('.tool-popup[data-tool-panel="move-rotate-panel"]')
  await expect(popup).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().activeClusterId)).toBe(ids[0])
  await popup.getByRole('button', { name: 'Clear selection', exact: true }).click()
  await expect(popup.locator('#mr-current-selection')).toHaveText('Nothing selected')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().activeClusterId)).toBeNull()
  await expect(popup.locator('#mr-tx')).toBeDisabled()
  await expect(popup.locator('#mr-session-hint')).toContainText('Select a cluster')
  await select(ids[1])
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().activeClusterId)).toBe(ids[1])
  await expect(popup.locator('#mr-tx')).toBeEnabled()
  await popup.getByRole('button', { name: 'Close Move / Rotate', exact: true }).click()
  expect(errors).toEqual([])
  expect(snapshot()).toEqual(before)
})
