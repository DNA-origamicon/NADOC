import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const PDB = [
  'ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00      PROA',
  'ATOM      2  CA  ALA     1       1.500   0.000   0.000  1.00  0.00      PROA',
  'ATOM      3  C   ALA     1       2.000   1.400   0.000  1.00  0.00      PROA',
  'ATOM      4  O   ALA     1       1.300   2.400   0.000  1.00  0.00      PROA',
  'ATOM      5  CB  ALA     1       2.000  -1.000   1.000  1.00  0.00      PROA',
  'ATOM      6  N   CYS     2       3.300   1.500   0.000  1.00  0.00      PROA',
  'ATOM      7  CA  CYS     2       4.100   2.700   0.000  1.00  0.00      PROA',
  'ATOM      8  CB  CYS     2       5.600   2.400   0.000  1.00  0.00      PROA',
  'ATOM      9  SG  CYS     2       6.700   3.900   0.000  1.00  0.00      PROA',
  'END',
].join('\n')

test('selected protein owns Tab and cycles translate/rotate gizmos', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=e2e-protein-gizmo-tab')
  await page.waitForSelector('#canvas')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__protein-gizmo-tab')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)

  await page.evaluate(pdb => window.__nadocTest.importProteinForTest(pdb), PDB)
  const proteinId = await page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.protein_attachments.at(-1).id)
  await page.evaluate(id => window.__nadocTest.selectProteinForTest(id), proteinId)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isProteinGizmoAttached())).toBe(true)

  const initialLevel = await page.evaluate(() => window.__nadocTest.getSelectionLevel())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getProteinGizmoMode())).toBe('translate')

  await page.evaluate(() => {
    const canvas = document.querySelector('#canvas')
    canvas.tabIndex = 0
    canvas.focus()
  })
  await page.keyboard.press('Tab')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getProteinGizmoMode())).toBe('rotate')
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe(initialLevel)

  await page.keyboard.press('Tab')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getProteinGizmoMode())).toBe('translate')
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe(initialLevel)
  expect(errors, errors.join('\n')).toEqual([])
})
