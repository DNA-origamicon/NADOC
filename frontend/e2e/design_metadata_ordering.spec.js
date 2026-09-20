import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Only persisted artifact: __e2e__metadata-ordering*.nadoc, removed by global teardown.
// Session cache is disabled by the e2e config; no external captures or simulation jobs.
test('a late design response applies geometry without reverting newer annotation metadata', async ({ page }) => {
  test.setTimeout(90_000)
  const doc = '__e2e__metadata-ordering'
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc, name: 'metadata-ordering' })
  const base = process.env.NADOC_E2E_API_BASE
  const response = await page.request.post(`${base}/api/design/helix-at-cell`, {
    headers: { 'X-NADOC-Doc': doc }, data: { row: 0, col: 1, length_bp: 40 },
  })
  expect(response.ok(), await response.text()).toBe(true)
  const geometryResponse = await page.request.get(`${base}/api/design/geometry`, {
    headers: { 'X-NADOC-Doc': doc },
  })
  expect(geometryResponse.ok(), await geometryResponse.text()).toBe(true)
  const lateDesign = { ...await response.json(), ...await geometryResponse.json() }
  expect(lateDesign.helix_axes).toHaveLength(2)
  // The backend has committed this edit; its response has not reached the store yet.
  const result = await page.evaluate(async json => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const metadata = await api.saveAnnotations({ annotations: [], enabled: false })
    await api._syncFromDesignResponse(json)
    const state = store.getState()
    return { newer: metadata.revision > json.revision,
      helices: state.currentDesign.helices.length,
      enabled: state.currentDesign.annotations_enabled,
      axes: Object.keys(state.currentHelixAxes ?? {}).length }
  }, lateDesign)
  expect(result).toEqual({ newer: true, helices: 2, enabled: false, axes: 2 })
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  await expect(page.locator('#right-panel .sidebar-column[data-panel-type="annotations"] [data-field="enabled"]')).not.toBeChecked()
  expect(errors, errors.join('\n')).toEqual([])
})
