import { expect } from '@playwright/test'

/** Reusable, headless driver for the user-visible oxDNA job workflow. */
export class OxdnaWizardDriver {
  constructor(page) {
    this.page = page
    this.modal = page.locator('.modal--oxdna-wizard')
  }

  async open(designFile, doc = `__e2e__oxdna-wizard-${Date.now()}`) {
    await this.page.goto(`/?doc=${doc}&open=${encodeURIComponent(designFile)}&open-type=design`)
    await this.page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
    await this.page.locator('.left-tab-btn[data-tab="dynamics"]').click()
    await this.page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
    await expect(this.page.locator('#oxdna-jobs-new-btn')).toBeEnabled({ timeout: 15_000 })
    await this.page.locator('#oxdna-jobs-new-btn').click()
    await expect(this.modal).toBeVisible()
    return this
  }

  async target(name) {
    await this.modal.locator(`.wiz-target-card[data-target="${name}"] > div`).first().click()
    if (name === 'alpine') {
      await this.page.evaluate(() => window.dispatchEvent(new CustomEvent(
        'nadoc:cluster-state-change', { detail: { state: 'connected' } })))
      await expect(this.modal.locator('.wiz-part-row[data-selectable="1"]').first()).toBeVisible()
    }
    if (name === 'runpod') {
      await expect(this.modal.locator('#wiz-target-runpod')).toBeVisible()
      await expect(this.modal.locator('.runpod-gpu-row').first()).toBeVisible()
      await expect(this.modal.locator('#wiz-runpod-recheck')).toHaveText('Re-check prices & stock')
    }
    return this
  }

  async tab(label) {
    await this.modal.locator('.wizard-tab', { hasText: label }).click()
    return this
  }

  async engine(label) {
    await this.tab('Parameters & options')
    await this.modal.locator('.oxdna-engine-options .wizard-preset', { hasText: label }).click()
    return this
  }

  async field(name, value) {
    const input = this.modal.locator(`[data-oxdna-field="${name}"]`)
    await input.fill(String(value))
    return this
  }

  async stageValue(rowLabel, stageColumn, value) {
    await this.tab('Full configuration')
    const row = this.modal.locator('.wizard-stages tr').filter({ hasText: rowLabel })
    const cell = row.locator('td').nth(stageColumn)
    await cell.click()
    const input = row.locator('input')
    await expect(input).toBeVisible()
    // Commit in one browser task: asynchronous hardware/pricing refreshes re-render the
    // table and can detach the transient editor between separate fill/press commands.
    await input.evaluate((node, next) => {
      node.value = next
      node.dispatchEvent(new Event('input', { bubbles: true }))
      node.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    }, String(value))
    await expect(row.locator('td').nth(stageColumn)).toContainText(String(value))
    return this
  }

  async create() {
    await this.tab('Full configuration')
    const button = this.modal.locator('.modal__actions button', { hasText: 'Create job' })
    await expect(button).toBeEnabled()
    await button.click()
  }
}
