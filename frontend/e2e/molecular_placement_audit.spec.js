import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FIXTURE = readFileSync(fileURLToPath(
  new URL('../../workspace/2hb_1xT.nadoc', import.meta.url)), 'utf8')

test('2hb_1xT molecular-placement audit renders four inspectable A/B panels', async ({ page }) => {
  test.setTimeout(120_000)
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))

  await page.goto('/?doc=e2e-molecular-placement-audit')
  await page.waitForSelector('#canvas')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)

  await page.evaluate(() => document.getElementById('menu-help-molecular-placement-audit')?.click())
  const modal = page.locator('#molecular-placement-audit')
  await expect(modal).toHaveClass(/visible/)
  await expect(modal.locator('.mpa-panel')).toHaveCount(4, { timeout: 90_000 })
  await expect(modal).toHaveAttribute('data-provider', 'crossover-insert-default-v2')
  await expect.poll(async () => Number(await modal.getAttribute('data-affected-atoms')))
    .toBeGreaterThan(0)

  expect(await modal.locator('.mpa-panel').evaluateAll(panels =>
    panels.map(panel => panel.dataset.panel)))
    .toEqual(['current', 'candidate', 'difference', 'defects'])
  const selectors = modal.locator('.mpa-representation')
  await expect(selectors).toHaveCount(4)
  for (let i = 0; i < 4; i++) {
    expect(await selectors.nth(i).locator('option').evaluateAll(options =>
      options.map(option => [option.value, option.textContent])))
      .toEqual([['full', 'Full'], ['ballstick', 'Ball and Stick']])
  }
  expect(await selectors.evaluateAll(nodes => nodes.map(node => node.value)))
    .toEqual(['full', 'full', 'ballstick', 'ballstick'])

  // A practical review layout: matched coarse views above, atom-level overlays below.
  await page.waitForTimeout(750)
  await expect(modal.locator('canvas')).toHaveCount(4)
  await expect(modal.locator('[data-panel="defects"] .mpa-defect-status'))
    .toContainText('No ring piercing or heavy-atom clash detected in either model.')
  await expect(modal.locator('[data-panel="defects"] .mpa-panel-title'))
    .toHaveText('Piercings / clashes')
  await modal.screenshot({ path: 'e2e/screenshots/molecular-placement-audit-2hb.png' })

  // Capture all four at the atomistic level as a quick visual strand-colour and
  // matched-camera regression. Detector annotation colours intentionally remain
  // layered over the underlying strand colours in Difference and Defects.
  for (let i = 0; i < 4; i++) {
    await selectors.nth(i).selectOption('ballstick')
    await expect(selectors.nth(i)).toHaveValue('ballstick')
  }
  await page.waitForTimeout(250)
  await expect(modal.locator('canvas')).toHaveCount(4)
  await modal.screenshot({ path: 'e2e/screenshots/molecular-placement-audit-2hb-atomistic.png' })

  // Exercise Full in the two annotation panels as well.
  for (const i of [2, 3]) {
    await selectors.nth(i).selectOption('full')
    await expect(selectors.nth(i)).toHaveValue('full')
  }
  await page.waitForTimeout(250)

  expect(pageErrors).toEqual([])
})
