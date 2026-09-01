import { expect, test } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('initial engine cards render on the first Simulations-tab open', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__engine-first-open', name: 'engine-first-open' })

  // Reproduce the reported first-open state: the selected tab says oxDNA while
  // its engine-specific panel still carries a stale hidden style.
  await page.evaluate(() => { document.getElementById('oxdna-jobs-panel').style.display = 'none' })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await expect(page.locator('#simulate-body')).toBeVisible()
  await expect(page.locator('.engine-selector-btn[data-engine="oxdna"]')).toHaveClass(/is-active/)

  const panel = page.locator('#oxdna-jobs-panel')
  await expect(panel).toBeVisible()
  const visibleCards = panel.locator(':scope #oxdna-jobs-body > .ox-card:visible')
  await expect(visibleCards).not.toHaveCount(0)
  for (const title of ['Clusters', 'Advanced', 'Anchors', 'Electric field',
    'Hard surface', 'Visualizations', 'Graphs and Metrics']) {
    await expect(visibleCards.locator('.ox-card__title', { hasText: title })).toBeVisible()
  }
  expect(errors, errors.join('\n')).toEqual([])
})
