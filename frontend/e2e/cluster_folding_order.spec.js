/** Persistence inventory: bundle + group commands stay in the isolated backend's
 * memory; no save/export. Session cache is disabled by Playwright config. Browser
 * preferences die with its context. Test-port bridge credentials and Playwright
 * reports/traces are removed by global teardown/artifact-cleanup-reporter.
 */
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

test('assigns cluster stages, collapses the card, and applies temperature-ordered routing', async ({ page, request }, testInfo) => {
  test.setTimeout(60000)
  const errors = trackConsoleErrors(page)
  const api = process.env.NADOC_E2E_API_BASE
  const headers = { 'X-NADOC-Doc': '__e2e__folding_order' }
  const response = await request.post(`${api}/api/design/bundle`, { headers, data: {
    name: '__e2e__Folding order', cells: [[0, 0], [0, 3], [0, 6]], length_bp: 84,
    lattice_type: 'HONEYCOMB', ligate_adjacent: false,
  } })
  expect(response.ok(), await response.text()).toBe(true)
  const original = (await response.json()).design
  for (const strand of original.strands.filter(s => s.strand_type === 'scaffold')) {
    const assigned = await request.post(`${api}/api/design/assign-scaffold-sequence`, { headers, data: { strand_id: strand.id } })
    expect(assigned.ok(), await assigned.text()).toBe(true)
  }
  for (let i = 0; i < 3; i++) {
    const created = await request.post(`${api}/api/design/cluster`, { headers, data: {
      name: `Folding cluster ${i + 1}`, helix_ids: [original.helices[i].id],
    } })
    expect(created.ok(), await created.text()).toBe(true)
  }
  await page.goto('/?doc=__e2e__folding_order&readiness=simulation')
  await page.waitForFunction(() => window.__nadocTest?.getDesignRenderer()?.getBackboneEntries()?.length > 0)
  await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
  const card = page.locator(':is(#cluster-folding-panel, [data-sidebar-source-id="cluster-folding-panel"]):visible').first()
  await page.getByRole('button', { name: 'Close Simulations sidebar', exact: true }).click()
  await page.getByRole('button', { name: 'Close Properties sidebar', exact: true }).click()
  // Open the card with enough horizontal room for the shared sidebar system.
  await expect(async () => {
    await page.locator('#right-tab-strip [data-tab="clustering"]').click()
    await expect(card).toBeVisible({ timeout: 1000 })
  }).toPass({ timeout: 10000 })
  const stage2 = card.getByRole('spinbutton', { name: 'Folding stage for Folding cluster 2', exact: true })
  const stage3 = card.getByRole('spinbutton', { name: 'Folding stage for Folding cluster 3', exact: true })
  await stage2.fill('1'); await stage2.press('Tab')
  await expect(card.locator('.folding-plan')).toContainText('Stage 1: Folding cluster 2')
  await stage3.fill('2'); await stage3.press('Tab')
  await expect(card.locator('.folding-plan')).toContainText('Stage 1: Folding cluster 2 → Stage 2: Folding cluster 3')
  await expect(card.getByRole('spinbutton', { name: 'Folding stage for Folding cluster 1', exact: true })).toHaveValue('')
  await card.getByRole('button', { name: 'Folding Order', exact: true }).click()
  await expect(stage2).toBeHidden()
  await card.getByRole('button', { name: 'Folding Order', exact: true }).click()
  await expect(stage2).toHaveValue('1')
  await page.evaluate(() => document.activeElement?.blur())
  await page.keyboard.press('2')
  const method = page.getByRole('dialog', { name: 'Autostaple method', exact: true })
  await method.getByLabel('Method', { exact: true }).selectOption('experimental')
  await method.getByRole('button', { name: 'OK', exact: true }).click()
  const modal = page.getByRole('dialog', { name: 'Experimental autostaple' })
  await expect(modal).toContainText('Stage 1: Folding cluster 2 → Stage 2: Folding cluster 3')
  await modal.getByLabel('Folding-order routing', { exact: true }).selectOption('ordered')
  await expect(modal.getByRole('button', { name: 'Apply', exact: true })).toBeEnabled()
  const done = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/full-autostaple')
  await modal.getByRole('button', { name: 'Apply', exact: true }).click()
  const routed = await done
  expect(routed.ok(), await routed.text()).toBe(true)
  const report = (await routed.json()).full_autostaple.experimental.folding_result
  const clusters = report.clusters.sort((a, b) => a.stage-b.stage)
  expect(clusters[0].median_c-clusters[1].median_c).toBeGreaterThanOrEqual(2)
  const results = page.getByRole('dialog', { name: 'Experimental autostaple results', exact: true })
  await expect(results).toContainText('achieved median gap')
  await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
  await page.screenshot({ path: testInfo.outputPath('folding-result.png') })
  await results.getByRole('button', { name: 'Close', exact: true }).last().click()
  // Server readback confirms the assignment is authored, rather than widget-only.
  const saved = await request.get(`${api}/api/design`, { headers })
  const design = (await saved.json()).design
  expect(design.cluster_transforms.find(c => c.name === 'Folding cluster 2').folding_order).toBe(1)
  expect(design.feature_log.at(-1).params.experimental.folding_order).toBe(true)
  expect(errors, errors.join('\n')).toEqual([])
})
