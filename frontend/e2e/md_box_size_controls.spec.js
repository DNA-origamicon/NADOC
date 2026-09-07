import { test, expect } from '@playwright/test'

test('box dimensions edit and reset in the real wizard without creating a job', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/__box_wizard_test__', route => route.fulfill({
    contentType: 'text/html', body: '<html><head><link rel="stylesheet" href="/src/styles/tokens.css"><link rel="stylesheet" href="/src/styles/components.css"></head><body></body></html>',
  }))
  await page.goto('/__box_wizard_test__')
  await page.evaluate(async () => {
    const { initJobWizard } = await import('/src/ui/md_job_wizard.js')
    const wizard = initJobWizard({
      api: {
        getRelaxPresets: async () => ({ presets: [{ id: 'literature', label: 'Literature' }] }),
        fetchHardware: async () => ({ summary: 'Test CPU' }),
        fetchProtocolPlan: async body => ({
          protocol: 'equilibrium_aware_namd', preset: { id: 'literature', label: 'Literature' },
          request: { box_mode: { value: 'bbox', provenance: 'default' },
            box_size_nm: { value: body.box_size_nm ?? null, provenance: body.box_size_nm ? 'user' : 'default' } },
          box_preview: { calculated_nm: [34, 12, 34], estimated: true },
          param_groups: [], stages: [], conditions: [], warnings: [], deferred: [],
          totals: { total_ns: 1 },
        }),
      },
      getJobs: () => [], getPartPath: () => null,
      launch: () => { throw new Error('This test must never launch a job') },
    })
    await wizard.open('relaxation')
  })
  await page.locator('.wizard-tab').nth(1).click()
  const box = page.getByTestId('box-size-controls')
  await expect(box.getByLabel('Box Y (nm)', { exact: true })).toHaveValue('12.000')
  await box.getByLabel('Box Y (nm)', { exact: true }).fill('24')
  await box.getByLabel('Box Y (nm)', { exact: true }).press('Tab')
  await expect(box.getByLabel('Box Y manually changed', { exact: true })).toBeVisible()
  await expect(box.getByLabel('Box X (nm)', { exact: true })).toHaveValue('34.000')
  await expect(box.getByLabel('Box Z (nm)', { exact: true })).toHaveValue('34.000')
  await box.getByRole('button', { name: 'Reset box size' }).click()
  await expect(box.getByLabel('Box Y (nm)', { exact: true })).toHaveValue('12.000')
  await expect(box.getByLabel('Box Y manually changed', { exact: true })).toHaveCount(0)
  expect(await box.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
  expect(errors).toEqual([])
})
