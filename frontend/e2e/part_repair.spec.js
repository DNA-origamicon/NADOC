import { test, expect } from '@playwright/test'

const DOC = '__e2e__part-recipe-repair'
const API = process.env.NADOC_E2E_API_BASE
const headers = { 'X-NADOC-Doc': DOC }
const jobs = new Set()

// Artifact inventory before invocation:
// - Own isolated backend/frontend ports from playwright.config.js, never :8000.
// - One __e2e__ in-memory document; any autosaved .nadoc/project revisions keep
//   that prefix and are removed by global-teardown.js/project_artifact_cleanup.
// - Session cache disabled by config. No source fixture, download, native build,
//   simulation or user file is read/written. Export/comparison bodies stay in
//   browser memory; the comparison owns one disposable WebGL context.
// - Private job IDs are cancelled below even after assertions fail, then the
//   document is dropped. Browser context owns its transient session/local storage.
// - Config may create failure traces/screenshots and Vite bridge credentials;
//   artifact-cleanup-reporter/global teardown own their cleanup. Root must verify
//   Archive-backed browser scratch/output before running and verify leftovers.
test.afterEach(async ({ page, request }) => {
  await page.close()
  try {
    for (const id of jobs) await request.delete(`${API}/api/design/features/evaluation/jobs/${encodeURIComponent(id)}`, { headers })
  } finally {
    jobs.clear()
    await request.delete(`${API}/api/documents/${DOC}`)
  }
})

test('saved native repair selects an exact reference and applies only its regenerated result', async ({ page }) => {
  test.setTimeout(120000)
  if (!API || /:8000(?:\/|$)/.test(API)) throw new Error('Use the dedicated isolated Playwright backend')
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', async response => {
    if (!/\/features\/(?:evaluation\/jobs|repair-draft\/evaluate)$/.test(response.url()) || !response.ok()) return
    try { const value = await response.json(); if (value.job_id) jobs.add(value.job_id) } catch { /* closed context */ }
  })
  await page.goto(`/?test=1&doc=${DOC}`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new'); await page.fill('#new-design-name', DOC)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()

  const fixture = await page.evaluate(async documentId => {
    const api = await import('/src/api/client.js')
    const first = await api.createGoldNanosphere(10)
    const second = await api.createGoldNanosphere(8)
    if (!first?.nanoparticle_id || !second?.nanoparticle_id) throw new Error('Native gold creation failed')
    await api.patchNanoparticle(first.nanoparticle_id, { diameter_nm: 12 })
    const response = await fetch('/api/design/export', { headers: { 'X-NADOC-Doc': documentId } })
    if (!response.ok) throw new Error('Could not capture the isolated native fixture')
    const text = await response.text()
    const source = JSON.parse(text), patch = source.feature_log.at(-1)
    if (patch.op_kind !== 'nanoparticle-patch' || patch.params.nanoparticle_id !== first.nanoparticle_id) throw new Error('Unexpected fixture history')
    // Replace only the last explicit owner reference in this tiny known recipe.
    // Keeping the original JSON text retains Python floats (12.0), so the real
    // browser scalar edit also exercises expected_old_json receipt transport.
    const needle = `"nanoparticle_id": "${first.nanoparticle_id}"`, at = text.lastIndexOf(needle)
    if (at < 0) throw new Error('Native patch reference was not present in exported JSON')
    const broken = text.slice(0, at) + '"nanoparticle_id": "__e2e__missing-particle"' + text.slice(at + needle.length)
    if (JSON.parse(broken).feature_log.at(-1).params.nanoparticle_id !== '__e2e__missing-particle') throw new Error('Fixture edit targeted a different reference')
    if (!await api.importDesign(broken)) throw new Error('Could not load the isolated broken recipe')
    return { first: first.nanoparticle_id, second: second.nanoparticle_id, designId: source.id,
      patchId: patch.id, published: source.nanoparticles }
  }, DOC)
  const particles = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.nanoparticles)
  await expect.poll(particles).toEqual(fixture.published)
  const open = async () => {
    await page.getByRole('button', { name: /^(?:Check \/ repair recipe|Repair · saved proposal)$/ }).click()
    const panel = page.getByRole('dialog').filter({ hasText: 'Check and repair part recipe' })
    await expect(panel.getByRole('button', { name: 'Reload saved proposal', exact: true })).toBeEnabled()
    return panel
  }
  let panel = await open()
  await panel.getByRole('button', { name: 'Check published recipe', exact: true }).click()
  await expect(panel.getByText('missing_reference:', { exact: false })).toBeVisible()
  await panel.getByRole('button', { name: 'Inspect failing input', exact: true }).first().click()
  await expect(panel.getByLabel('Feature to repair')).toHaveValue(JSON.stringify([fixture.patchId, null]))
  await panel.getByRole('button', { name: 'Find replacements', exact: true }).click()
  await panel.getByRole('button', { name: new RegExp(`\\(${fixture.second}\\)$`) }).click()
  await panel.getByLabel('Diameter (nm)', { exact: true }).fill('14')
  await panel.locator(`[data-repair-path='["diameter_nm"]']`).getByRole('button', { name: 'Add proposed change', exact: true }).click()
  await panel.getByRole('button', { name: 'Save proposal', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Evaluate proposal', exact: true })).toBeEnabled()
  await expect.poll(particles).toEqual(fixture.published)

  await panel.getByRole('button', { name: 'Close', exact: true }).click()
  await page.reload()
  await expect.poll(() => page.evaluate(() => window.__nadocTest?.store.getState().currentDesign?.id)).toBe(fixture.designId)
  panel = await open()
  await expect(panel.locator('.part-repair__proposal li')).toHaveCount(2)
  await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeDisabled()
  await panel.getByRole('button', { name: 'Evaluate proposal', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeEnabled({ timeout: 15000 })
  await expect.poll(particles).toEqual(fixture.published)
  const geometryBefore = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentGeometry))
  const comparisonResponse = page.waitForResponse(response => /\/features\/evaluation\/jobs\/[^/]+\/comparison$/.test(response.url()))
  await panel.getByRole('button', { name: 'Compare authored geometry', exact: true }).click()
  const compared = await comparisonResponse
  expect(compared.ok()).toBe(true)
  const projection = await compared.json()
  expect(projection.coverage.complete).toBe(true)
  expect(projection.coverage.scientific_qualification).toBe(false)
  expect(projection.published.particles.map(p => [p.id, p.diameter_nm])).toEqual([[fixture.first, 12], [fixture.second, 8]])
  expect(projection.proposed.particles.map(p => [p.id, p.diameter_nm])).toEqual([[fixture.first, 10], [fixture.second, 14]])
  const comparison = panel.getByRole('region', { name: 'Private proposal comparison' })
  await expect(comparison.getByText('Published authored geometry · unverified', { exact: true })).toBeVisible()
  await expect(comparison.getByText('Evaluated proposal', { exact: true })).toBeVisible()
  await expect(comparison.locator('canvas')).toBeVisible()
  await expect.poll(particles).toEqual(fixture.published)
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentGeometry))).toBe(geometryBefore)
  const exported = await page.evaluate(async documentId => {
    const response = await fetch('/api/design/export', { headers: { 'X-NADOC-Doc': documentId } })
    if (!response.ok) throw new Error('Could not inspect published export during comparison')
    return (await response.json()).nanoparticles
  }, DOC)
  expect(exported).toEqual(fixture.published)
  await comparison.getByRole('button', { name: 'Fit comparison', exact: true }).click()
  await comparison.getByRole('button', { name: 'Close comparison', exact: true }).click()
  await expect(comparison.locator('canvas')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeEnabled()
  await panel.getByRole('button', { name: 'Compare authored geometry', exact: true }).click()
  await expect(comparison.locator('canvas')).toBeVisible()
  await panel.getByRole('button', { name: 'Cancel evaluation', exact: true }).click()
  await expect(comparison.locator('canvas')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeDisabled()
  await panel.getByRole('button', { name: 'Evaluate proposal', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeEnabled({ timeout: 15000 })
  await panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true }).click()
  const diameters = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.nanoparticles.map(p => [p.id, p.diameter_nm]))
  await expect.poll(diameters).toEqual([[fixture.first, 10], [fixture.second, 14]])
  await panel.getByRole('button', { name: 'Check published recipe', exact: true }).click()
  await expect(panel.locator('.part-repair > [role="status"]')).toContainText('regenerated successfully', { timeout: 15000 })
  await panel.getByRole('button', { name: 'Evaluate proposal', exact: true }).click()
  await expect(panel.locator('.part-repair > [role="alert"]')).toContainText(/rebase/i)
  await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeDisabled()
  await panel.getByRole('button', { name: 'Close', exact: true }).click()

  await page.evaluate(async () => { await (await import('/src/api/client.js')).undo() })
  await expect.poll(particles).toEqual(fixture.published)
  panel = await open()
  await expect(panel.locator('.part-repair__proposal li')).toHaveCount(2)
  await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeDisabled()
  await panel.getByRole('button', { name: 'Discard proposal', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Evaluate proposal', exact: true })).toBeDisabled()
  await expect.poll(particles).toEqual(fixture.published)
  expect(errors).toEqual([])
})
