import { expect, test } from '@playwright/test'

test('graphene-only card points to rendered reservoir and ion settings in wizard', async ({ page }) => {
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.locator('#menu-file-new').evaluate(el => el.click())
  await page.fill('#new-design-name', '__e2e__graphene-controls')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name)).toBe('__e2e__graphene-controls')
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  if (await page.locator('#simulate-body').evaluate(el => getComputedStyle(el).display === 'none')) await page.click('#simulate-heading')
  await page.click('.engine-selector-btn[data-engine="namd"]')

  await page.click('#md-surface-toggle')
  await page.locator('#md-hard-surface-settings > summary').click()
  await expect(page.locator('#md-surface-axis')).toBeVisible()
  await expect(page.locator('#md-surface-offset')).toBeVisible()
  await expect(page.locator('#md-surface-dna-clearance')).toBeVisible()
  await expect(page.locator('#md-surface-pore-diameter')).not.toBeVisible()
  await expect(page.locator('#md-surface-enable')).not.toBeChecked()
  await page.check('#md-surface-enable')
  await page.locator('#md-nanopore-settings > summary').click()
  await expect(page.locator('#md-surface-pore-diameter')).toBeVisible()
  await expect(page.locator('#md-surface-graphene-only')).toHaveCount(0)
  await expect(page.locator('#md-surface-enable').locator('..')).toHaveAttribute('title', /New job → Protocol & settings/)
  // These belong to the job/solvent package, not the geometric surface descriptor.
  await expect(page.locator('#md-surface-body')).not.toContainText('Ionic conditionsCustom')

  await page.click('#md-jobs-new-btn')
  await page.getByRole('tab', { name: /Protocol & settings/ }).click()
  await expect(page.locator('.wizard-field__label', { hasText: 'Water padding' })).toBeVisible()
  await expect(page.locator('.wizard-field__label', { hasText: 'Ionic conditions' })).toBeVisible()
  await expect(page.locator('.wizard-field__label', { hasText: 'NaCl' })).toBeVisible()
  await expect(page.locator('.wizard-field__label', { hasText: 'Magnesium' })).toBeVisible()
})

// UI-only: no design saves, job creation, or remote execution.
test('changing files clears a manually enabled graphene nanopore', async ({ page }) => {
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await expect(page.locator('#md-surface-enable')).not.toBeChecked()
  await page.evaluate(() => {
    const checkbox = document.getElementById('md-surface-enable')
    checkbox.checked = true
    checkbox.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await expect(page.locator('#md-surface-enable')).toBeChecked()
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:workspace-path-change')))
  await expect(page.locator('#md-surface-enable')).not.toBeChecked()
  await expect(page.locator('#md-surface-ready')).toContainText('Surface off')
})
