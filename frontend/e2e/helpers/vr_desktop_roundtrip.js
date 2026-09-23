import { expect } from '@playwright/test'
import { demoReview } from './vr_demo.js'
import { writeFile } from 'node:fs/promises'

// Operates only on the caller's isolated __e2e__ document/workspace.
export async function verifyVRDesktopRoundTrip(page, request, testInfo, original, { doc = '__e2e__vr-native-confirm', expectedBases = original.helices.length*42*2, newCellLength = 42, editCell = [1,1] } = {}) {
  const originalCount = original.helices.length
  const visibleCount = original.helices.filter(h=>h.lattice_frame_id===original.lattice_frames[0].id).length
  const base = process.env.NADOC_E2E_API_BASE
  const headers = { 'X-NADOC-Doc': doc }
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  const editor = await page.context().newPage()
  await editor.goto(`/cadnano-editor.html?doc=${doc}`)
  if (original.lattice_frames.length>1) await editor.getByLabel('Lattice frame',{exact:true}).selectOption(original.lattice_frames[0].id)
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(visibleCount)
  await editor.locator(`.sv-cell.empty[data-row="${editCell[0]}"][data-col="${editCell[1]}"]`).click({timeout:10000})
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(visibleCount+1)
  const edited = await editor.evaluate(async () =>
    (await import('/src/cadnano-editor/store.js')).editorStore.getState().design)
  const added = edited.helices.filter(h => !original.helices.some(old => old.id === h.id))
  expect(added).toHaveLength(1)
  expect(added[0]).toMatchObject({ grid_pos:editCell, length_bp:newCellLength, lattice_frame_id:original.lattice_frames[0].id })
  expect(edited.helices.filter(h => h.id !== added[0].id)).toEqual(original.helices)
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.helices.length)).toBe(originalCount+1)
  // The cadnano cell tool creates an empty helix (populate_strands:false).
  // Existing DNA must survive unchanged; adding a cell adds no nucleotides.
  expect(edited.strands).toEqual(original.strands)
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentGeometry.length)).toBe(expectedBases)
  const before = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    return { design:store.getState().currentDesign,
      positions:store.getState().currentGeometry.map(n => n.backbone_position) }
  })
  expect(before.positions).toHaveLength(expectedBases)
  // Library hides roots starting '__'; teardown also reserves e2e__ filenames.
  // The design name retains __e2e__, and the entire workspace is disposable.
  const filename = 'e2e__VR-roundtrip.nadoc'
  const saved = await page.evaluate(async filename =>
    (await import('/src/api/client.js')).saveDesignToWorkspace(filename), filename)
  expect(saved).toBeTruthy()
  const file = await request.get(`${base}/api/library/content`, { headers, params:{ path:filename } })
  expect(file.status()).toBe(200)
  const content = (await file.json()).content
  const onDisk = JSON.parse(content)
  expect(onDisk.strands).toEqual(before.design.strands)
  expect(onDisk.helices).toEqual(before.design.helices)
  expect(onDisk.lattice_frames).toEqual(before.design.lattice_frames)
  expect(onDisk.cluster_transforms).toEqual(before.design.cluster_transforms)
  await editor.screenshot({ path:testInfo.outputPath('cadnano-edited.png') })
  await demoReview(editor,'cadnano geometry and cell edit')
  await editor.close()
  // Import the saved file into a separate document, not the original live state.
  const reloaded = await page.context().newPage()
  await reloaded.goto('/?doc=__e2e__vr-roundtrip-reloaded')
  await reloaded.locator(`[data-library-path="${filename}"]`).click({ timeout:10000 })
  await expect(reloaded.locator('#welcome-screen')).not.toBeVisible({ timeout:10000 })
  const after = await reloaded.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    return { design:store.getState().currentDesign,
      positions:store.getState().currentGeometry.map(n => n.backbone_position) }
  })
  expect(after.design.strands).toEqual(before.design.strands)
  expect(after.design.helices).toEqual(before.design.helices)
  expect(after.design.lattice_frames).toEqual(before.design.lattice_frames)
  expect(after.design.cluster_transforms).toEqual(before.design.cluster_transforms)
  expect(after.positions).toEqual(before.positions)
  await reloaded.waitForFunction(() => {
    let visible=false
    window.__nadocTest?.scene?.traverse(o => { if (o.isInstancedMesh && o.count>0) visible=true })
    return visible
  })
  await reloaded.locator('#canvas').click({ position:{ x:30,y:30 }, timeout:10000 })
  await reloaded.keyboard.press('f')
  await reloaded.screenshot({ path:testInfo.outputPath('reloaded-desktop.png') })
  await demoReview(reloaded,'saved part reloaded in desktop 3D')
  await testInfo.attach('roundtrip', { contentType:'application/json', body:JSON.stringify({
    saved_file:filename, helices:after.design.helices.length, bases:after.positions.length,
    edited_cell:added[0].grid_pos, frame_id:added[0].lattice_frame_id,
  }) })
  // Preserve the exact verified saved bytes as a review output. A separate
  // publication step may copy this into the editable VR workspace; tests never
  // read that workspace as their oracle.
  await writeFile(testInfo.outputPath('review-part.nadoc'), content)
  await reloaded.close()
}
