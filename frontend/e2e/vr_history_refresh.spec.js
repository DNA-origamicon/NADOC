import { test, expect } from '@playwright/test'

// Persistent inventory: __e2e__ part/autosave project snapshots in an isolated
// workspace, removed by global-teardown even on failure. Session caching is off.
// VR transport is intercepted: this never takes over the user's physical viewer.
test('native history events seek desktop geometry and publish the committed revision to VR', async ({ page }, info) => {
  await page.setViewportSize({ width: 1600, height: 1000 })
  const published = [], refreshes = [], accepted = []
  // The native session registry is machine-wide, including across test backends.
  await page.route('**/api/vr/**', route => route.fulfill({ json: { running: false } }))
  await page.route('**/api/vr/feature-log', async route => {
    published.push(route.request().postDataJSON())
    await route.fulfill({ json: { published: true } })
  })
  await page.route('**/api/vr/scene-refresh', async route => {
    const body = route.request().postDataJSON()
    refreshes.push(body)
    const response = await page.request.get(route.request().url().replace('/vr/scene-refresh', '/design'), { headers: { 'X-NADOC-Doc': '__e2e__vr-history' } })
    const current = await response.json()
    const valid = body.expected_design_id === current.design.id && body.expected_revision === current.revision
    await route.fulfill({ status: valid ? 200 : 422, json: valid ? { published: true, scene_revision: current.revision } : { detail: 'Missing or stale design identity/revision' } })
    if (valid) accepted.push(body)
  })
  await page.goto('/?test=1&doc=__e2e__vr-history&scrywrite=inspect')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR history refresh')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    if (!await api.createBundle({ cells: [[0, 0]], lengthBp: 32, plane: 'XY' })) throw Error('fixture bundle failed')
    if (!await api.addBundleSegment({ cells: [[3, 0]], lengthBp: 32, plane: 'XY', ligateAdjacent: false })) throw Error('fixture segment failed')
  })
  const read = () => page.evaluate(() => import('/src/state/store.js').then(({ store }) => {
    const s = store.getState()
    return { id: s.currentDesign.id, helices: s.currentDesign.helices.length, cursor: s.currentDesign.feature_log_cursor, geometry: s.currentGeometry.length }
  }))
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const points = store.getState().currentGeometry.map(n => n.backbone_position)
    const low = [0, 1, 2].map(i => Math.min(...points.map(p => p[i])))
    const high = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])))
    const target = low.map((v, i) => (v + high[i]) / 2)
    const span = Math.max(...high.map((v, i) => v - low[i]), 10)
    window.__nadocTest.applyCameraPoseForTest({ target, position: target.map((v, i) => v + span * [1, 0.7, 2][i]) })
  })
  const before = await read()
  expect(before.helices).toBe(2)
  for (const [sequence, id, count] of [[1, 'r:1', 1], [2, 'r:2', 2]]) {
    await page.evaluate(() => window.__nadocTest.scrywrite.publishFeatureHistory())
    const version = published.at(-1).version
    await page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event), { type: 'feature_log', sequence, version, id })
    await expect.poll(async () => (await read()).helices).toBe(count)
    await expect.poll(() => accepted.length).toBe(sequence)
    expect(refreshes).toHaveLength(sequence)
    expect(refreshes.at(-1).expected_design_id).toBe(before.id)
    expect(Number.isSafeInteger(refreshes.at(-1).expected_revision)).toBe(true)
    await expect.poll(() => published.at(-1).busy).toBe(false)
    expect(published.at(-1).status).not.toContain('failed')
    const state = await read()
    expect(state.geometry).toBeGreaterThan(0)
    await page.screenshot({ path: info.outputPath(`history-${sequence}.png`) })
  }
  expect(refreshes[1].expected_revision).toBeGreaterThan(refreshes[0].expected_revision)
})
