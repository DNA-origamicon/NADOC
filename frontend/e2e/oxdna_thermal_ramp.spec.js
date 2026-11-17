/** UI-only exercise. Reads an existing design, never creates or starts a job.
 * __e2e__ session/autosave files are removed by global-teardown; screenshots
 * stay in Playwright's output directory and are removed by its cleanup reporter.
 */
import { expect, test } from '@playwright/test'

test('production wizard toggles heating, cooling and observable stability', async ({ page }, testInfo) => {
  if (process.env.NADOC_THERMAL_VISUAL_REVIEW) test.setTimeout(120000)
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await page.goto('/?doc=__e2e__thermal-ramp&open=2hb_1xT.nadoc&open-type=design')
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await page.locator('#oxdna-jobs-new-btn').click()
  const wizard = page.locator('.modal--oxdna-wizard')
  await wizard.locator('.wizard-mode', { hasText: 'Production' }).click()
  await wizard.locator('[data-thermal-field="enabled"]').check()
  await expect(wizard.locator('[data-thermal-field="gate"]')).toBeChecked()
  for (const width of [1440, 760, 480]) {
    await page.setViewportSize({ width, height: 1000 })
    const layout = await wizard.locator('[data-thermal-controls]').evaluate(root => {
      const bounds = root.getBoundingClientRect()
      return {
        overflow: root.scrollWidth > root.clientWidth + 1,
        inputsFit: [...root.querySelectorAll('input')].every(input => {
          const box = input.getBoundingClientRect()
          return box.left >= bounds.left && box.right <= bounds.right
        }),
        checkboxGap: [...root.querySelectorAll('input[type="checkbox"]')].map(input =>
          input.nextElementSibling.getBoundingClientRect().left - input.getBoundingClientRect().right),
        aligned: [...root.querySelectorAll('.oxdna-thermal__grid')].every(grid => {
          const inputs = [...grid.querySelectorAll('input')].map(input => input.getBoundingClientRect())
          return getComputedStyle(grid).gridTemplateColumns.split(' ').length === 1
            || inputs.every(input => Math.abs(input.top - inputs[0].top) < 1)
        }),
      }
    })
    expect(layout.overflow).toBe(false)
    expect(layout.inputsFit).toBe(true)
    expect(layout.aligned).toBe(true)
    expect(layout.checkboxGap.every(gap => gap >= 4 && gap <= 12)).toBe(true)
  }
  if (process.env.NADOC_THERMAL_VISUAL_REVIEW) {
    await expect(page.locator('#op-progress')).not.toHaveClass(/visible/, { timeout: 15000 })
    await page.setViewportSize({ width: 1440, height: 1000 })
    await wizard.locator('.modal__body').evaluate(node => { node.scrollTop = 0 })
    await page.screenshot({ path: testInfo.outputPath('thermal-desktop.png') })
    await page.setViewportSize({ width: 760, height: 900 })
    await wizard.locator('[data-thermal-controls]').scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('thermal-narrow.png') })
    await page.setViewportSize({ width: 480, height: 900 })
    await wizard.locator('[data-thermal-controls]').scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('thermal-small.png') })
    console.log('THERMAL_VISUAL_READY', testInfo.outputPath('thermal-desktop.png'))
    await page.waitForTimeout(45000) // bounded visual review; cleanup reporter removes both images
    await page.setViewportSize({ width: 1280, height: 720 })
  }

  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(wizard.locator('[data-job-temperature]')).toBeHidden()
  await expect(wizard.locator('[data-oxdna-field="steps"]')).toBeDisabled()
  await wizard.locator('[data-thermal-field="start_c"]').fill('85')
  await wizard.locator('[data-thermal-field="start_c"]').press('Tab')
  await wizard.locator('[data-thermal-field="end_c"]').fill('25')
  await wizard.locator('[data-thermal-field="end_c"]').press('Tab')
  await wizard.locator('.wizard-tab', { hasText: 'Summary' }).click()
  const config = wizard.locator('.oxdna-wizard-config')
  await expect(config).toContainText('temperature = 358.15K')
  await expect(config).toContainText('temperature = 298.15K')
  await expect(config).toContainText('13_thermal')
  await expect(config).toContainText('"gate":true')
  await wizard.locator('.wizard-tab', { hasText: 'Run parameters' }).click()
  await wizard.locator('[data-thermal-field="gate"]').uncheck()
  await expect(wizard.locator('[data-thermal-field="max_steps"]')).toHaveCount(0)
  await wizard.locator('[data-thermal-field="enabled"]').uncheck()
  await expect(wizard.locator('[data-job-temperature]')).toBeVisible()
  await expect(wizard.locator('[data-oxdna-field="steps"]')).toBeEnabled()
  expect(errors).toEqual([])
})
