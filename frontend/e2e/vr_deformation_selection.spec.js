import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Inventory: __e2e__ parts/history removed by global teardown; session cache is
// disabled. Mixed-selection review PNGs are intentionally retained under
// .development-artifacts/vr-multiselect-preview; other screenshots use the cleanup reporter. No viewer
// or runtime files: only headset transport is intercepted, mutations are real.
for (const mode of ['bend', 'twist']) for (const scope of ['cluster', 'strand', 'domain', 'mixed']) {
  test(`VR ${mode} ${scope} multiselection, exact commit, persistence and Undo`, async ({ page }, info) => {
    test.setTimeout(90000)
    const feedback = [], preflight = [], execution = [], planes = []
    const errors = trackConsoleErrors(page)
    page.on('response', async response => { if (response.status() >= 400) console.log('HTTP', response.status(), response.url(), await response.text()) })
    for (const [route, output] of [['feedback', feedback], ['tool-preflight-feedback', preflight], ['tool-execution-feedback', execution], ['plane-feedback', planes]])
      await page.route(`**/api/vr/${route}`, async request => {
        output.push(request.request().postDataJSON())
        await request.fulfill({ json: { acknowledged: true, published: true } })
      })
    await page.route('**/api/vr/scene-refresh', route => route.fulfill({ json: { published: true, scene_revision: 1 } }))
    await loadScaffoldedPart(page, { doc: `__e2e__vr-${mode}-${scope}`, name: `vr-${mode}-${scope}`, extraQuery: '&scrywrite=1' })
    const identities = await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      await api.addBundleSegment({ cells: [[0,1], [0,2]], lengthBp: 200 })
      const d = structuredClone(window.__nadocTest.store.getState().currentDesign)
      d.strands = d.helices.flatMap((h, i) => [
        { id: `selected-${i}`, strand_type: 'scaffold', domains: [
          { helix_id: h.id, start_bp: 0, end_bp: 99, direction: 'FORWARD' },
          { helix_id: h.id, start_bp: 100, end_bp: 199, direction: 'FORWARD' }] },
        { id: `stationary-${i}`, strand_type: 'staple', domains: [{ helix_id: h.id, start_bp: 0, end_bp: 199, direction: 'REVERSE' }] }])
      d.cluster_transforms = d.helices.map((h,i) => ({ id: `c-${i}`, name: `Cluster ${i}`, helix_ids: [h.id],
        domain_ids: [{ strand_id: `selected-${i}`, domain_index: 1 }] }))
      d.feature_log = []; d.feature_log_cursor = -1; d.deformations = []; d.loadouts = []; d.active_loadout_id = null
      await api.importDesign(JSON.stringify(d))
      window.__nadocTest.applyCameraPoseForTest({ target: [0,0,45], position: [115,35,45] })
      return d.helices.map((h,i) => `nuc:selected-${i}:1:${h.id}:150:FORWARD:0:slab`)
    })
    await page.waitForTimeout(500) // Allow the imported scene's renderer rebuild before VR picking.
    const dispatch = event => page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event), event)
    let sequence = 0
    for (let i = 0; i < identities.length; i++) {
      const level = scope === 'mixed' ? ['cluster', 'strand', 'domain'][i] : scope
      await dispatch({ type: 'selection_level', level })
      await dispatch({ type: 'select', sequence: ++sequence, identities: [identities[i]] })
      await expect.poll(() => feedback.length).toBe(sequence)
    }
    const target = feedback.at(-1)
    expect(target.selection_kind, JSON.stringify({ feedback, selection: await page.evaluate(() => window.__nadocTest.getCanonicalSelection()), geometry: await page.evaluate(() => window.__nadocTest.store.getState().currentGeometry.slice(0,1)) })).toBe('selection')
    expect(target.selected_owner_tokens).toHaveLength(3)
    const refs = await page.evaluate(() => window.__nadocTest.getCanonicalSelection().items)
    const read = () => page.evaluate(async () => ({
      design: window.__nadocTest.store.getState().currentDesign,
      geometry: (await (await import('/src/api/client.js'))._request('GET','/design/geometry')).nucleotides,
    }))
    const before = await read()
    const draft = { mode, target_kind: target.selection_kind, target_identity: target.identity, target_owner_tokens: target.owner_tokens,
      plane_a_bp: null, plane_b_bp: null, angle_deg: 60, direction_deg: 0, amount_mode: 'total_degrees', amount: -60 }
    await dispatch({ type: 'tool_config', sequence: 1, draft })
    for (const [i, slot] of ['a','b'].entries()) {
      await dispatch({ type: 'plane_pick', sequence: i+1, toolConfigSequence: 1, slot, extent: slot, identity: target.identity })
      await expect.poll(() => planes.length).toBe(i+1)
      expect(planes.at(-1).resolved).toBe(true)
    }
    expect(planes.map(p => p.plane_bp)).toEqual([scope === 'strand' || scope === 'mixed' ? 0 : 100, 199])
    Object.assign(draft, { plane_a_bp: planes[0].plane_bp, plane_b_bp: planes[1].plane_bp })
    await dispatch({ type: 'tool_config', sequence: 2, draft })
    await expect.poll(() => preflight.some(p => p.tool_config_sequence === 2 && ['ok','warn'].includes(p.status))).toBe(true)
    const event = { type: 'tool', sequence: 1, configSequence: 2, mode, action: 'confirm', targetIdentity: target.identity,
      targetKind: target.selection_kind, targetOwnerTokens: target.owner_tokens }
    await dispatch(event)
    await expect.poll(() => execution.some(e => e.tool_sequence === 1 && e.status === 'succeeded')).toBe(true)
    const after = await read()
    expect(after.design.deformations).toHaveLength(1)
    expect(after.design.deformations[0].targets).toEqual(refs)
    const selected = n => n.direction === 'FORWARD' && (scope === 'strand' || (scope === 'mixed' && n.strand_id === 'selected-1') || n.bp_index >= 100)
    expect(after.geometry.filter(n => !selected(n))).toEqual(before.geometry.filter(n => !selected(n)))
    expect(after.geometry.filter(selected)).not.toEqual(before.geometry.filter(selected))
    const evidence = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.development-artifacts/vr-multiselect-preview')
    if (scope === 'mixed') fs.mkdirSync(evidence, { recursive: true })
    await page.screenshot({ path: scope === 'mixed' ? path.join(evidence, `${mode}.png`) : info.outputPath(`${mode}-${scope}.png`) })
    await dispatch({ ...event, sequence: 2, action: 'undo' })
    await expect.poll(() => execution.some(e => e.tool_sequence === 2 && e.status === 'succeeded')).toBe(true)
    expect((await read()).geometry).toEqual(before.geometry)
    // A delayed Confirm cannot act on a set with a removed non-primary member.
    await page.evaluate(async () => {
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      const store = window.__nadocTest.store
      createSelectionController({ store }).replace(store.getState().selection.items.slice(1))
    })
    await dispatch({ ...event, sequence: 3 })
    await expect.poll(() => execution.some(e => e.tool_sequence === 3 && e.status === 'refused')).toBe(true)
    expect((await read()).design.deformations).toHaveLength(0)
    const filename = await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      await api.redo()
      const filename = window.__nadocTest.store.getState().currentDesign.metadata.identity_last_known_path
      if (!filename) throw new Error('Fixture has no workspace path')
      if (!await api.saveDesignToWorkspace(filename)) throw new Error('Save failed')
      return filename
    })
    await page.evaluate(async absolute => (await import('/src/api/client.js')).loadDesign(absolute),
      path.join(process.env.NADOC_WORKSPACE ?? path.resolve('../workspace'), filename))
    await expect.poll(async () => { try { return (await read()).geometry } catch { return null } }).toEqual(after.geometry)
    expect((await read()).design.deformations[0].target_ranges).toEqual(after.design.deformations[0].target_ranges)
    expect(errors).toEqual([])
  })
}
