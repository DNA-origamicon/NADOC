/** Browser exercise for the shared strand display identity contract. */

import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('spreadsheet and Properties show the same short strand ID', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: 'e2e-display-labels', name: 'display-labels' })

  await page.locator('#sheet-toggle').click()
  await expect(page.locator('#spreadsheet-thead-row th').first()).toHaveText('ID')

  const row = page.locator('#spreadsheet-tbody tr').first()
  const idCell = row.locator('td[data-col="id"]')
  await expect(idCell).toHaveText('X1')
  await idCell.click()

  const strandProperty = page.locator('#properties-content .prop-row').first()
  await expect(strandProperty.locator('.prop-label')).toHaveText('strand')
  await expect(strandProperty.locator('.prop-val')).toHaveText('X1')
  expect(errors, errors.join('\n')).toEqual([])
})
