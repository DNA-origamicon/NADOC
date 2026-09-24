import { test, expect } from '@playwright/test'

// Inventory: only __e2e__ autosaved parts in NADOC_WORKSPACE (temporary directory).
// Global teardown removes parts; caller removes temporary directory even on failure.
// This exercises the authoring API, not a simulated controller workflow trial.
test('empty part accepts an undoable frame extrusion and an oblique second frame', async ({ page }, testInfo) => {
  const doc = '__e2e__vr-frame-commit'
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`/?doc=${doc}`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR frame commit')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  const outcomes = await page.evaluate(async doc => {
    const api = await import('/src/api/client.js')
    const headers = { 'X-NADOC-Doc': doc, 'Content-Type': 'application/json' }
    const invoke = async (path, body) => {
      const response = await fetch(`/api/design/${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
      return { status: response.status, data: await response.json() }
    }
    const initial = await api.getDesign()
    const body = { expected_design_id: initial.design.id, expected_revision: initial.revision,
      cells: [[0,0],[0,1]], length_bp: 42, plane: 'XY' }
    const { evaluateVRToolPreflight } = await import('/src/scene/vr_tool_execution_plan.js')
    const preflight = await invoke('frame-extrusion/validate', body)
    const nativeDraft = {
      mode: 'extrude', target_kind: 'none', target_identity: null, target_owner_tokens: [],
      length_bp: 42, direction_sign: 1, strand_filter: 'both', ligate_adjacent: true,
      footprint_state: 'unresolved', extrude_from: 'XY',
      painted_footprint: { lattice_type: initial.design.lattice_type, cells: [[0,0],[0,1]] },
    }
    const painted = await evaluateVRToolPreflight(5, nativeDraft, { design: initial.design, api })
    const { createVRToolPreflightCoordinator } = await import('/src/scene/vr_tool_preflight_coordinator.js')
    const published = []
    // Native feedback transport is isolated; validation uses the real backend.
    const coordinator = createVRToolPreflightCoordinator({
      sendFeedback: async feedback => { published.push(feedback); return { published: true } },
    })
    await coordinator.request(5, nativeDraft, { design: initial.design, api })
    const wrongSequence = coordinator.takeValidatedPlan(4)
    const retained = coordinator.takeValidatedPlan(5)
    const repeated = coordinator.takeValidatedPlan(5)
    const stillEmpty = (await api.getDesign()).design.helices.length
    const firstData = await api.addFrameExtrusion(body)
    const first = { status: firstData ? 201 : 0, data: firstData }
    const repeat = await invoke('frame-extrusion', body)
    const freeform = await evaluateVRToolPreflight(6, { ...nativeDraft,extrude_from:'XZ',
      freeform_placement:{ translation_nm:[14,0,0],rotation_xyzw:[Math.sin(Math.PI/8),0,0,Math.cos(Math.PI/8)] },
    }, { design:first.data.design,api })
    if (freeform.feedback.status!=='ok') throw new Error(`Freeform preflight: ${freeform.feedback.reason}`)
    const secondData = await api.addFrameExtrusion(freeform.plan.commit.arguments)
    const second = { status: secondData ? 201 : 0, data: secondData }
    return { initial: initial.design, preflight, painted, wrongSequence, retained, repeated, published, stillEmpty, first, repeat, second }
  }, doc)
  expect(outcomes.initial.helices).toEqual([])
  expect(outcomes.preflight.status).toBe(200)
  expect(outcomes.painted.feedback).toMatchObject({ status: 'ok', target_kind: 'none', tool_config_sequence: 5 })
  expect(outcomes.painted.plan.commit.arguments.expected_revision).toBe(outcomes.first.data.revision - 1)
  expect(outcomes.stillEmpty).toBe(0)
  expect(outcomes.wrongSequence).toBeNull()
  expect(outcomes.repeated).toBeNull()
  expect(outcomes.retained).toEqual(outcomes.painted.plan)
  expect(outcomes.published.at(-1)).toMatchObject({ status: 'ok', tool_config_sequence: 5 })
  expect(outcomes.first.status).toBe(201)
  expect(outcomes.repeat.status).toBe(409)
  expect(outcomes.second.status).toBe(201)
  const design = outcomes.second.data.design
  expect(design.helices).toHaveLength(4)
  expect(design.lattice_frames).toHaveLength(2)
  expect(design.feature_log.filter(f => f.op_kind === 'extrude-frame')).toHaveLength(2)
  expect(design.cluster_transforms[1].translation).toEqual([14,0,0])
  await page.waitForFunction(() => {
    let visible = false
    window.__nadocTest?.scene?.traverse(o => { if (o.isInstancedMesh && o.count > 0) visible = true })
    return visible
  })
  await page.locator('#canvas').click({ position: { x: 30, y: 30 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(300) // Camera framing animation for review capture.
  await page.screenshot({ path: testInfo.outputPath('committed-desktop.png') })
  const headers = { 'X-NADOC-Doc': doc }
  const exported = await page.request.get(`${process.env.NADOC_E2E_API_BASE}/api/design/export/cadnano`, { headers })
  expect(exported.status()).toBe(200)
  expect(new Set((await exported.json()).vstrands.map(h => `${h.row}:${h.col}`)).size).toBe(4)
  const editor = await page.context().newPage()
  await editor.goto(`/cadnano-editor.html?doc=${doc}`)
  await editor.getByLabel('Lattice frame', { exact: true }).selectOption(design.lattice_frames[1].id)
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(2)
  await editor.close()
  const undo = await page.request.post(`${process.env.NADOC_E2E_API_BASE}/api/design/undo`, { headers })
  expect((await undo.json()).design.helices).toHaveLength(2)
  const redo = await page.request.post(`${process.env.NADOC_E2E_API_BASE}/api/design/redo`, { headers })
  expect((await redo.json()).design.helices).toHaveLength(4)
  // Extend the oblique frame itself, rather than adding another frame at origin.
  const extension = await page.evaluate(async frameId => {
    const api = await import('/src/api/client.js')
    const current = await api.getDesign()
    const { evaluateVRToolPreflight } = await import('/src/scene/vr_tool_execution_plan.js')
    const resolved = await evaluateVRToolPreflight(9, {
      mode:'extrude', target_kind:'none', target_identity:null, target_owner_tokens:[],
      length_bp:42, direction_sign:1, strand_filter:'both', ligate_adjacent:true,
      footprint_state:'unresolved', extrude_from:'XZ',
      painted_footprint:{ lattice_type:current.design.lattice_type, cells:[[1,0]] },
    }, { design:current.design, api })
    if (resolved.feedback.status !== 'ok' || resolved.plan.commit.arguments.source_frame_id !== frameId) {
      throw new Error('Existing source plane was not validated')
    }
    return api.addFrameExtrusion(resolved.plan.commit.arguments)
  }, design.lattice_frames[1].id)
  expect(extension.design.helices).toHaveLength(5)
  expect(extension.design.lattice_frames).toEqual(design.lattice_frames)
  expect(extension.design.helices.slice(0,4)).toEqual(design.helices)
  expect(extension.design.helices[4].lattice_frame_id).toBe(design.lattice_frames[1].id)
  expect(extension.design.cluster_transforms[1].translation).toEqual([14,0,0])
  expect(extension.design.cluster_transforms[1].rotation).toEqual(design.cluster_transforms[1].rotation)
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentGeometry.length)).toBe(5*42*2)
  await page.keyboard.press('f')
  await page.screenshot({ path:testInfo.outputPath('extended-frame-desktop.png') })
  const updatedEditor = await page.context().newPage()
  await updatedEditor.goto(`/cadnano-editor.html?doc=${doc}`)
  await updatedEditor.getByLabel('Lattice frame', { exact:true }).selectOption(design.lattice_frames[1].id)
  await expect(updatedEditor.locator('.sv-cell.occupied')).toHaveCount(3)
  await updatedEditor.screenshot({ path:testInfo.outputPath('extended-frame-cadnano.png') })
  await updatedEditor.close()
  const selected = extension.design.helices.find(h => h.lattice_frame_id===design.lattice_frames[1].id)
  const endResult = await page.evaluate(async selected => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const { resolveVREndToolContext } = await import('/src/scene/vr_tool_context.js')
    const { evaluateVRToolPreflight } = await import('/src/scene/vr_tool_execution_plan.js')
    await api.getDesign() // Synchronize after the separate cadnano document client.
    const state = store.getState()
    const n = state.currentGeometry.find(n => n.helix_id===selected.id && n.bp_index===41 &&
      (n.is_three_prime || n.is_five_prime))
    if (!n) throw new Error('No live terminal nucleotide')
    const selectedRef = { kind:'end', key:`${n.helix_id}:${n.bp_index}:${n.direction}` }
    const resolved = resolveVREndToolContext(selectedRef, { design:state.currentDesign,
      geometry:state.currentGeometry, domainEnds:window.__nadocTest.getVRToolEndTable() })
    if (!resolved.accepted) throw new Error(`End context refused: ${resolved.reason}`)
    const identity = `nuc:${selectedRef.key}`
    const ownerTokens = ['owner:end-diagnostic']
    const draft = { mode:'extrude', target_kind:'end', target_identity:identity,
      target_owner_tokens:ownerTokens, length_bp:21, direction_sign:1,
      strand_filter:'both', ligate_adjacent:false, footprint_state:'unresolved',
      extrude_from:resolved.context.plane }
    const preflight = await evaluateVRToolPreflight(10,draft,{ design:state.currentDesign,
      geometry:state.currentGeometry, api, toolTarget:{ identity,selectionKind:'end',
        ownerTokens,selectedRef,toolContext:resolved.context } })
    if (preflight.feedback.status!=='ok') throw new Error(`End preflight refused: ${preflight.feedback.reason}`)
    const { createVRPaintedCommit } = await import('/src/scene/vr_painted_commit.js')
    const { createVRToolTransactionCoordinator } = await import('/src/scene/vr_tool_transaction.js')
    let retained = preflight.plan
    const feedback = []
    let refreshes = 0
    const executor = createVRPaintedCommit({
      preflight:{ takeValidatedPlan:seq => { if (seq!==10) return null; const p=retained; retained=null; return p } },
      transaction:createVRToolTransactionCoordinator({ getState:store.getState,undoDesign:api.undo }),
      api:{ ...api,refreshNativeVRScene:async () => { refreshes++; return { published:true } } },
      getState:store.getState,resolveTarget:() => ({ identity,selectionKind:'end',ownerTokens }),
      sendFeedback:async (...args) => { feedback.push(args); return { published:true } },
    })
    const event = { mode:'extrude',action:'confirm',targetKind:'end',targetIdentity:identity,
      targetOwnerTokens:ownerTokens,sequence:1,configSequence:10 }
    const outcome = await executor.handle(event)
    if (!outcome.accepted) throw new Error(`End commit refused: ${outcome.reason}`)
    const repeat = await executor.handle(event)
    return { design:store.getState().currentDesign,context:resolved.context,plan:preflight.plan,
      feedback:feedback.map(args=>args[1]),refreshes,repeat }

  }, selected)
  expect(endResult.context).toMatchObject({ sourceFrameId:selected.lattice_frame_id,
    plane:'XZ',offsetNm:selected.axis_end.y,deformed:false })
  expect(endResult.plan.commit.arguments.sourceFrameId).toBe(selected.lattice_frame_id)
  expect(endResult.feedback).toEqual(['pending','succeeded'])
  expect(endResult.refreshes).toBe(1)
  expect(endResult.repeat.reason).toBe('invalid_or_stale')
  const continued = endResult.design
  expect(continued.helices).toHaveLength(5)
  expect(continued.helices.find(h => h.id===selected.id)).toMatchObject({
    length_bp:63, grid_pos:selected.grid_pos, lattice_frame_id:selected.lattice_frame_id,
  })
  expect(continued.helices.filter(h => h.id!==selected.id)).toEqual(extension.design.helices.filter(h => h.id!==selected.id))
  expect(continued.cluster_transforms).toEqual(extension.design.cluster_transforms)
  await page.evaluate(async () => (await import('/src/api/client.js')).getDesign())
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentGeometry.length)).toBe(462)
  await page.locator('#canvas').click({ position:{ x:400,y:300 } })
  await page.keyboard.press('Escape')
  await page.keyboard.press('f')
  await page.mouse.move(650,400)
  await page.mouse.wheel(0,150) // Review framing: margin around the extended tip.
  await page.waitForTimeout(300) // Bounded camera damping, outside measured input.
  await page.screenshot({ path:testInfo.outputPath('continued-frame-desktop.png') })
  const continuedExport = await page.request.get(`${process.env.NADOC_E2E_API_BASE}/api/design/export/cadnano`, { headers })
  const exportedLengths = (await continuedExport.json()).vstrands.map(h => h.scaf.filter(b => b.some(n => n!==-1)).length).sort((a,b)=>a-b)
  expect(exportedLengths).toEqual([42,42,42,42,63])
  expect(errors).toEqual([])
})
