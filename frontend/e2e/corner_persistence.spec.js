import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Native editor commands and its Save/Load routes only. The __e2e__ part,
// revision stores and browser captures are removed by global teardown/reporter;
// session caching is disabled by the shared Playwright configuration.
test.use({ trace: 'off' })
test('Corner delete/revert undo and saved recipe independently verify', async ({ page }) => {
  test.setTimeout(120_000)
  const doc = '__e2e__corner-persistence'
  const errors = trackConsoleErrors(page)
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill(doc)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(doc => window.__nadocTest.store.getState().currentDesign?.metadata?.name === doc, doc)
  await page.evaluate(async doc => {
    const api = await import('/src/api/client.js')
    const corner = await import('/src/api/corner.js')
    await api.createBundle({ cells: [[0, 0], [0, 1]], lengthBp: 84,
      name: doc, latticeType: 'HONEYCOMB' })
    const saveHold = api.holdFeatureEditSaves()
    try {
      await saveHold.ready
      const source = window.__nadocTest.store.getState().currentDesign
      const identity = corner.captureCornerSource(source)
      const parameters = { cluster_id: source.cluster_transforms[0].id, position_bp: 42, angle_deg: 90, direction_deg: 15 }
      let token
      await corner.previewCorner(identity, parameters, { onEvent(event) { if (event.type === 'ready') token = event.preview_token } })
      const result = await corner.applyCorner(identity, parameters, token)
      if (!result.corner.reused_preview) throw new Error('Apply did not use the prepared Corner')
    } finally { saveHold.release() }
  }, doc)
  const featureId = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1).id)
  const before = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length - 1)
  await page.locator('#fl-list button[title="Delete this feature"]').last().click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.helices.length)).toBe(2)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1).id)).toBe(featureId)
  await page.locator('#fl-list button[title^="Revert to before Corner:"]').last().click()
  await page.getByRole('button', { name: 'Revert', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.helices.length)).toBe(2)
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)).toBe(before)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.helices.length)).toBe(4)
  const persisted = await page.evaluate(async doc => {
    const api = await import('/src/api/client.js')
    const fields = ['helices', 'strands', 'forced_ligations', 'deformations']
    const snapshot = () => {
      const design = window.__nadocTest.store.getState().currentDesign
      return { ...Object.fromEntries(fields.map(key => [key, structuredClone(design[key])])),
        features: design.feature_log.map(row => ({ id: row.id, kind: row.op_kind, params: row.params })) }
    }
    await api.saveDesignToWorkspace(`${doc}.nadoc`)
    const before = snapshot()
    await api.loadDesign(`workspace/${doc}.nadoc`)
    return { before, reopened: snapshot() }
  }, doc)
  expect(persisted.reopened).toEqual(persisted.before)
  expect(persisted.reopened.features.at(-1).kind).toBe('corner')
  const headers = { 'X-NADOC-Doc': doc }
  const start = await page.request.post('/api/design/features/verification/jobs', { headers })
  expect(start.status()).toBe(202)
  const { job_id: job } = await start.json()
  let result
  await expect.poll(async () => {
    result = await (await page.request.get(`/api/design/features/verification/jobs/${job}`, { headers })).json()
    return result.status
  }, { timeout: 15_000 }).toBe('complete')
  expect(result.stale).toBe(false)
  expect(result.result).toMatchObject({ status: 'verified', native_editable: true })
  expect(errors).toEqual([])
})
