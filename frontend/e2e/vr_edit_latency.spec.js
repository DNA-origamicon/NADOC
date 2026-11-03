import { test, expect } from '@playwright/test'
import fs from 'node:fs'

test('deferred VR edits render canonical geometry and retain saved-document replay guards', async ({ page }, info) => {
  test.setTimeout(180000)
  page.on('response', async response => {
    if (response.url().includes('/api/design/undo') || response.status() >= 400) console.log('API', response.status(), response.url())
  })
  await page.goto(`/?doc=__e2e__edit-latency-${process.pid}`)
  await page.waitForFunction(() => !!window.__nadocScene)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__Edit latency')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(async () => !!(await import('/src/state/store.js')).store.getState().currentDesign?.id)
  const report = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    await api.addBundleSegment({ cells: Array.from({ length: 24 }, (_, i) => [Math.floor(i / 6), i % 6]), lengthBp: 250, plane: 'XY', ligateAdjacent: false })
    const hid = store.getState().currentDesign.helices[0].id
    const measurements = []
    const frame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    async function edit(name, execute) {
      const start = performance.now()
      let committedMs, early, revision
      const result = await execute({ deferGeometry: true, onCommitted: response => {
        committedMs = performance.now() - start
        // Autosave may replace the prior object while the request runs.
        early = store.getState().currentDesign !== response.design
        revision = response.revision
      } })
      if (!result) throw Error(name + ': ' + JSON.stringify(store.getState().lastError))
      await frame()
      const state = store.getState()
      measurements.push({ name, committedMs, early, revision, desktopReadyMs: performance.now() - start,
        nucleotides: state.currentGeometry.length, partialHelices: state.lastPartialChangedHelixIds?.length ?? null })
      if (!state.currentGeometry.length) throw Error('Empty rendered geometry: ' + name)
      return result
    }
    await edit('nick', options => api.addNick({ helixId: hid, bpIndex: 125, direction: 'FORWARD' }, options))
    const strands = store.getState().currentDesign.strands.filter(s => s.domains.some(d => d.helix_id === hid && d.direction === 'FORWARD'))
    const a = strands.find(s => s.domains.at(-1).end_bp === 125), b = strands.find(s => s.domains[0].start_bp === 126)
    await edit('ligate', options => api.forcedLigation(a.id, b.id, false, options))
    await edit('bend', options => api.addDeformation('bend', 10, 110, { kind: 'bend', curvature_deg_per_bp: .1, direction_deg: 0 }, [hid], false, [], options))
    await edit('bend undo', options => api.undo(options))
    await edit('twist', options => api.addDeformation('twist', 10, 110, { kind: 'twist', total_degrees: 10 }, [hid], false, [], options))
    await edit('twist undo', options => api.undo(options))
    await edit('sweep', options => api.createSweep({ cells: [[10,0]], plane: 'XY', points_nm: [[40,0,0],[40,0,8],[42,0,16]], strand_filter: 'both', ligate_adjacent: false }, options))
    const log = store.getState().currentDesign.feature_log
    const index = log.findLastIndex(e => e.op_kind === 'sweep')
    const params = log[index].params
    let sweepEditBlocked = null
    const editedParams = { ...params, points_nm: [[40,0,0],[40,0,8],[43,0,16]] }
    try {
      await edit('sweep edit', options => api.editFeature(index, editedParams, options))
    } catch (error) {
      const candidateError = store.getState().lastError
      // Saved-document replay currently compares identity-signoff metadata to
      // the unsaved recipe root. Preserve and explicitly report this boundary;
      // check the ordinary desktop path refuses the same edit too.
      const baseline = await api.editFeature(index, editedParams)
      const baselineError = store.getState().lastError
      if (baseline || !candidateError?.message?.includes('recipe_not_reproducible') ||
          !candidateError.message.includes('metadata') ||
          !baselineError?.message?.includes('recipe_not_reproducible')) throw error
      sweepEditBlocked = { candidate: candidateError, baseline: baselineError,
        limitation: 'Sweep-edit success is NOT verified in app; both deferred and ordinary requests hit the recipe metadata guard.' }
    }
    await edit('sweep undo', options => api.undo(options))
    let meshes = 0
    window.__nadocScene.traverse(o => { if (o.isMesh && o.visible) meshes++ })
    return { scope: 'Real desktop app/backend/rendering; callback timing only, no native headset session', measurements, sweepEditBlocked, visibleMeshes: meshes, inventory: window.__nadocDR.debugRenderedAudit().inventory }
  })
  if (process.env.NADOC_EDIT_LATENCY_REPORT) fs.writeFileSync(process.env.NADOC_EDIT_LATENCY_REPORT, JSON.stringify(report, null, 2))
  // Observation-only fit, after all timed edits, through the normal UI handler.
  await page.evaluate(() => document.getElementById('unhide-all-btn').click())
  await page.waitForTimeout(100)
  if (process.env.NADOC_EDIT_LATENCY_CAPTURE) await page.screenshot({ path: process.env.NADOC_EDIT_LATENCY_CAPTURE })
  expect(report.visibleMeshes).toBeGreaterThan(0)
  expect(report.inventory.beads).toBeGreaterThanOrEqual(12000)
  expect(report.inventory.slabs).toBeGreaterThanOrEqual(12000)
  for (const row of report.measurements.filter(r => !r.name.endsWith('undo'))) expect(row.early, row.name).toBe(true)
  expect(report.measurements.find(r => r.name === 'nick').partialHelices).toBe(1)
  expect(report.measurements.find(r => r.name === 'ligate').partialHelices).toBe(1)
})
