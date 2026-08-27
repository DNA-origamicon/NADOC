/** Frontend-only oxDNA wizard exercise. Never clicks Create job. */
import { expect, test } from '@playwright/test'

const DOC = '__e2e__oxdna-wizard'
const OPEN_URL = `/?doc=${DOC}&open=2hb_1xT.nadoc&open-type=design`

async function openWizard(page) {
  await page.goto(OPEN_URL)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await expect(page.locator('#oxdna-jobs-new-btn')).toBeEnabled({ timeout: 15_000 })
  await expect(page.locator('#oxdna-jobs-run-btn')).toBeDisabled()
  await page.locator('#oxdna-jobs-new-btn').click()
  await expect(page.locator('.modal--oxdna-wizard')).toBeVisible()
  return page.locator('.modal--oxdna-wizard')
}

test('oxDNA wizard exposes matching hardware targets and a complete three-step config flow', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  let creates = 0
  page.on('pageerror', error => errors.push(String(error)))
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/oxdna/jobs') creates++
  })

  const wizard = await openWizard(page)
  await expect(wizard.locator('.wizard-tab')).toHaveCount(3)
  await expect(wizard.locator('.wizard-tab').nth(0)).toHaveText('Where it runs')
  await expect(wizard.locator('.wiz-target-card')).toHaveCount(3)
  await expect(wizard.locator('.wiz-target-card[data-target="local"]')).toBeVisible()
  await expect(wizard.locator('.wiz-target-card[data-target="alpine"]')).toBeVisible()
  await expect(wizard.locator('.wiz-target-card[data-target="runpod"]')).toBeVisible()

  // Alpine mounts the same authentication/availability component as the NAMD wizard.
  await wizard.locator('.wiz-target-card[data-target="alpine"] > div').first().click()
  await expect(wizard.locator('.wiz-target-card[data-target="alpine"]')).toContainText(/Sign in|Connected|Connecting/i)
  await expect(wizard.locator('#wiz-target-alpine-rows')).toBeVisible()

  // Return to the always-ready local target and exercise the parameter/config tabs.
  await wizard.locator('.wiz-target-card[data-target="local"] > div').first().click()
  await wizard.locator('.wizard-tab', { hasText: 'Parameters & options' }).click()
  const mdSteps = wizard.locator('[data-oxdna-field="md_relax_steps"]')
  await expect(mdSteps).toHaveValue('1000000')
  await mdSteps.fill('2500000')
  await wizard.locator('[data-oxdna-field="salt_concentration"]').fill('0.25')

  await wizard.locator('.wizard-tab', { hasText: 'Full configuration' }).click()
  const config = wizard.locator('.oxdna-wizard-config')
  await expect(config).toContainText('execution_target = local')
  await expect(config).toContainText('# 1_mc_relax:')
  await expect(config).toContainText('# 2_md_relax:')
  await expect(config).toContainText('steps = 2500000')
  await expect(config).toContainText('salt_concentration = 0.25')
  await expect(config).toContainText('# 3_equil:')
  await expect(wizard.locator('.modal__actions button', { hasText: 'Create job' })).toBeVisible()

  expect(creates).toBe(0)
  expect(errors, errors.join('\n')).toEqual([])
})
