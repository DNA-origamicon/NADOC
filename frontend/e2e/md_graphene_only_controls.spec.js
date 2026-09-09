import { expect, test } from '@playwright/test'

test('graphene-only card points to rendered reservoir and ion settings in wizard', async ({ page }) => {
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.evaluate(() => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.querySelectorAll('.left-tab-btn').forEach(button => { button.disabled = false })
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    document.querySelectorAll('.tab-content').forEach(element => {
      element.hidden = element.id !== 'tab-content-dynamics'
    })
  })
  await page.click('.engine-selector-btn[data-engine="namd"]')

  await page.click('#md-surface-toggle')
  await expect(page.locator('#md-surface-axis')).toBeVisible()
  await expect(page.locator('#md-surface-offset')).toBeVisible()
  await expect(page.locator('#md-surface-dna-clearance')).toBeVisible()
  await expect(page.locator('#md-surface-pore-diameter')).not.toBeVisible()
  await expect(page.locator('#md-surface-enable')).not.toBeChecked()
  await page.check('#md-surface-enable')
  await expect(page.locator('#md-surface-pore-diameter')).toBeVisible()
  await expect(page.locator('#md-surface-graphene-only')).toHaveCount(0)
  await expect(page.locator('#md-surface-body')).toContainText('New job → 2 Setup → Settings')
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
  await expect(page.locator('#md-surface-ready')).toContainText('Off')
})
