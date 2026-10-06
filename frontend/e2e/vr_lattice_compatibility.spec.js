import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// __e2e__ parts and history: global teardown; session cache disabled. Optional
// supplied part is read only and imported into an isolated workspace. Keep its ID
// because historical snapshots carry it; rewriting only the top-level ID makes
// Undo switch document identities and races document-specific background reads.
// The workflow intentionally retains NADOC_COMPAT_SCREENSHOT in its artifact directory.
test('VR lattice compatibility: old segments, new extrusion, Undo and save/reopen', async ({ page }, info) => {
  test.setTimeout(90000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const errors = trackConsoleErrors(page)
  const rejectedReads = []
  page.on('response', response => {
    if (response.status() >= 400) rejectedReads.push((async () => ({
      status: response.status(), url: response.url(), text: await response.text(),
    }))())
  })
  await loadScaffoldedPart(page, { doc: '__e2e__lattice-compat', name: 'lattice-compat' })
  const supplied = process.env.NADOC_COMPAT_PART ? fs.readFileSync(process.env.NADOC_COMPAT_PART, 'utf8') : await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: Array.from({ length: 8 }, (_, i) => [0, i]), lengthBp: 88,
      name: '__e2e__lattice-compat', latticeType: 'SQUARE' })
    await api.addBundleSegment({ cells: [[-1,0], [-1,1]], lengthBp: 120 })
    const old = structuredClone(window.__nadocTest.store.getState().currentDesign)
    old.helices.slice(8).forEach(h => { h.lattice_frame_id = null })
    return JSON.stringify(old)
  })
  const savePath = path.resolve(process.env.NADOC_WORKSPACE || '../workspace', '__e2e__lattice-compat.nadoc')
  const result = await page.evaluate(async ({ supplied, savePath }) => {
    const api = await import('/src/api/client.js')
    const { buildPaintedExtrusionPlan } = await import('/src/scene/vr_painted_extrusion_plan.js')
    const read = () => structuredClone(window.__nadocTest.store.getState().currentDesign)
    const old = JSON.parse(supplied)
    old.metadata.name = '__e2e__lattice-compat'
    old.metadata.identity_last_known_path = savePath
    old.loadouts = []; old.active_loadout_id = null; old.last_editable_loadout_id = null
    await api.importDesign(JSON.stringify(old))
    const repaired = read()
    const config = { extrude_from: 'XY', length_bp: 24, direction_sign: 1, strand_filter: 'both',
      painted_footprint: { lattice_type: repaired.lattice_type, cells: [[2,0]] } }
    const plan = buildPaintedExtrusionPlan(config, repaired, api.currentRevisionWatermark())
    if (!plan.accepted) throw Error(plan.reason)
    await api.validateFrameExtrusion(plan.plan.preflight.arguments)
    await api.addFrameExtrusion(plan.plan.commit.arguments)
    const extruded = read()
    await api.undo(); const undone = read()
    await api.redo(); const redone = read()
    const path = savePath
    await api.saveDesign(path); await api.loadDesign(path)
    // Document-specific reads must succeed once replacement has settled.
    const query = '?document_id=' + encodeURIComponent(read().id)
    await api._request('GET', '/design/dimensions' + query)
    await api._request('GET', '/design/view-volumes' + query)
    return { old, repaired, extruded, undone, redone, reopened: read() }
  }, { supplied, savePath })
  expect(result.repaired.helices).toHaveLength(10)
  expect(result.repaired.helices.every(h => h.lattice_frame_id === result.repaired.lattice_frames[0].id)).toBe(true)
  expect(result.repaired.cluster_transforms).toEqual(result.old.cluster_transforms)
  expect(result.repaired.deformations).toEqual(result.old.deformations)
  expect(result.extruded.helices).toHaveLength(11)
  expect(result.undone.id).toBe(result.repaired.id)
  expect(result.redone.id).toBe(result.repaired.id)
  expect(result.undone.helices).toEqual(result.repaired.helices)
  expect(result.reopened.helices).toEqual(result.redone.helices)
  expect(result.reopened.deformations).toEqual(result.repaired.deformations)
  await page.evaluate(() => {
    const points = Object.values(window.__nadocTest.store.getState().currentHelixAxes).flatMap(a => [a.start, a.end])
    const low = [0,1,2].map(i => Math.min(...points.map(p => p[i])))
    const high = [0,1,2].map(i => Math.max(...points.map(p => p[i])))
    const target = low.map((v,i) => (v + high[i]) / 2)
    const distance = Math.max(10, Math.hypot(...high.map((v,i) => v-low[i]))) * 1.3
    window.__nadocTest.applyCameraPoseForTest({ target,
      position: target.map((v,i) => v + [0.55,-0.9,0.4][i] * distance), up: [0,0,1], fov: 45 })
  })
  await page.waitForTimeout(500)
  await page.screenshot({ path: process.env.NADOC_COMPAT_SCREENSHOT || info.outputPath('repaired-part.png') })
  // Open/import/load may reject an outstanding read during document replacement,
  // including reopening the same ID. Stable reads above must succeed afterward.
  // Assert the exact guard response, not a blanket 409 allow.
  const rejected = await Promise.all(rejectedReads)
  for (const response of rejected) {
    const url = new URL(response.url)
    expect(response.status, response.text).toBe(409)
    expect(['/api/design/dimensions', '/api/design/view-volumes']).toContain(url.pathname)
    expect(url.searchParams.get('document_id')).toBeTruthy()
    expect(['Measurement document is no longer active.', 'View-volume document is no longer active.'])
      .toContain(JSON.parse(response.text).detail)
  }
  const expectedConsole = 'Failed to load resource: the server responded with a status of 409 (Conflict)'
  expect(errors.filter(error => error === expectedConsole)).toHaveLength(rejected.length)
  expect(errors.filter(error => error !== expectedConsole)).toEqual([])
})
