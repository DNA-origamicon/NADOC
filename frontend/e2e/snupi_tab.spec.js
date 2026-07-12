// Exercises the SNUPI FEM engine tab wiring in the running app: the tab appears as a
// sibling of CanDo/mrDNA/oxDNA/NAMD, its panel + relocated run controls render, the
// capability strip greys the unsupported Hard-surface card, and the Advanced (material
// selector) / Anchors / Electric-field cards all toggle open — with zero console errors.
//
// End-to-end job SUBMISSION + the FEM display overlay are covered by the real-solve
// backend tests (tests/test_snupi_job.py: create → run → completed + cached display/RMSF)
// and the panel's pure-fn unit tests (snupi_jobs_panel.test.js); driving a full job through
// the UI needs a doc-scoped paired-bundle build, which hits the known multi-doc build
// friction (MV-28 family) the CanDo/oxDNA panels are documented against too.
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

test('SNUPI engine tab renders + its cards toggle in the running app', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  const doc = 'snupitab'

  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__snupi')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })

  // Dynamics tab → the SNUPI engine tab (a first-class sibling of the other engines).
  await page.click('[data-tab="dynamics"]')
  await page.waitForTimeout(300)
  const snupiTab = page.locator('.engine-selector-btn[data-engine="snupi"]')
  await expect(snupiTab).toBeVisible()
  await expect(snupiTab).toContainText('SNUPI')
  await snupiTab.click()

  // The SNUPI panel + its relocated run controls show; sibling panels are hidden.
  await expect(page.locator('#snupi-jobs-panel')).toBeVisible()
  await expect(page.locator('#snupi-jobs-coarse-btn')).toBeVisible()
  await expect(page.locator('#snupi-jobs-fine-btn')).toBeVisible()
  await expect(page.locator('#cando-jobs-panel')).toBeHidden()

  // The capability strip greys the unsupported Hard-surface card for SNUPI (no wall BC),
  // while anchors + electric field are supported (not greyed).
  await expect(page.locator('.capability-chip.is-greyed', { hasText: 'Hard surface' })).toBeVisible()

  // Advanced drawer → the SNUPI material-variant selector (SNUPI vs CanDo baseline).
  await page.click('#snupi-jobs-adv-toggle')
  await expect(page.locator('#snupi-jobs-material')).toBeVisible()
  await expect(page.locator('#snupi-jobs-material option')).toHaveCount(2)
  await expect(page.locator('#snupi-jobs-n-steps')).toBeVisible()
  await expect(page.locator('#snupi-jobs-with-rmsf')).toBeVisible()

  // Anchors + Electric-field cards toggle open (the shared oxDNA-anchor + forces cards,
  // wired to the SNUPI ids → predict_shape(anchors=, field=)).
  await page.click('#snupi-anchors-toggle')
  await expect(page.locator('#snupi-anchors-body')).toBeVisible()
  await page.click('#snupi-efield-toggle')
  await expect(page.locator('#snupi-efield-body')).toBeVisible()
  await page.check('#snupi-efield-enable')
  await page.fill('#snupi-efield-mag', '0.2')
  // With a field but no anchor the ready line warns (non-blocking, same as CanDo).
  await expect(page.locator('#snupi-efield-ready')).toContainText(/no anchor|pN/i)

  // The viz radios exist and stay locked until a completed job is selected.
  await expect(page.locator('.snupi-display-mode[value="deform"]')).toBeDisabled()
  await expect(page.locator('.snupi-display-mode[value="cando"]')).toBeDisabled()

  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
