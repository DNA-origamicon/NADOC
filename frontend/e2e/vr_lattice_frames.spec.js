import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'

// Inventory: fresh in-memory candidate; autosaves have __e2e__ names and are
// removed by global teardown. Screenshot/input evidence uses testInfo.outputPath.
// Run with NADOC_WORKSPACE pointing at a disposable directory.
test('independent lattice cells retain poses through desktop import and cadnano export', async ({ page }, testInfo) => {
  const code = `
import math
from backend.core.models import Design
from backend.core.lattice_frames import append_independent_bundle
x=append_independent_bundle(Design(),[[0,0],[0,1]],42,name='First frame')
x=append_independent_bundle(x,[[0,0],[0,1]],42,translation_nm=[14,0,0],rotation_xyzw=[0,math.sin(math.pi/8),0,math.cos(math.pi/8)],name='Second frame')
x.metadata.name='__e2e__VR lattice frames'
print(x.to_json())
`
  const content = execFileSync('uv', ['run','python','-c',code],
    { cwd: path.resolve(process.cwd(),'..'), encoding: 'utf8' })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/?doc=__e2e__vr-lattice-frames')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR frame review')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  const loaded = await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    const { store } = await import('/src/state/store.js')
    const s = store.getState()
    return { frames: s.currentDesign.lattice_frames, helices: s.currentDesign.helices,
      clusters: s.currentDesign.cluster_transforms, count: s.currentGeometry?.length }
  }, content)
  expect(loaded.frames).toHaveLength(2)
  expect(loaded.helices).toHaveLength(4)
  expect(loaded.count).toBeGreaterThan(0)
  const source = JSON.parse(content)
  for (const frame of source.lattice_frames) {
    expect(loaded.frames).toContainEqual(frame)
    expect(loaded.clusters.find(c => c.id === frame.placement_cluster_id))
      .toEqual(source.cluster_transforms.find(c => c.id === frame.placement_cluster_id))
  }
  const exported = await page.request.get(`${process.env.NADOC_E2E_API_BASE}/api/design/export/cadnano`,
    { headers: { 'X-NADOC-Doc': '__e2e__vr-lattice-frames' } })
  expect(exported.status()).toBe(200)
  const json = await exported.json()
  expect(new Set(json.vstrands.map(h => `${h.row}:${h.col}`)).size).toBe(4)
  await page.waitForFunction(() => {
    let visible = false
    window.__nadocTest?.scene?.traverse(o => { if (o.isInstancedMesh && o.count > 0) visible = true })
    return visible
  })
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.locator('#canvas').click({ position: { x: 30, y: 30 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(300) // Allow camera framing animation before review capture.
  await page.screenshot({ path: testInfo.outputPath('frames-desktop.png') })
  await testInfo.attach('candidate.nadoc', { body: content, contentType: 'application/json' })
  const editor = await page.context().newPage()
  editor.on('pageerror', error => errors.push(error.message))
  await editor.goto('/cadnano-editor.html?doc=__e2e__vr-lattice-frames')
  const picker = editor.getByLabel('Lattice frame', { exact: true })
  await expect(picker).toBeVisible()
  await picker.selectOption(source.lattice_frames[1].id)
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(2)
  const beforeIds = source.helices.filter(h => h.lattice_frame_id === source.lattice_frames[0].id).map(h => h.id)
  await editor.locator('.sv-cell.empty[data-row="0"][data-col="2"]').click()
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(3)
  const edited = await editor.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design)
  const added = edited.helices.find(h => !source.helices.some(old => old.id === h.id))
  expect(added.lattice_frame_id).toBe(source.lattice_frames[1].id)
  expect(added.grid_pos).toEqual([0, 2])
  expect(edited.cluster_transforms.find(c => c.id === source.lattice_frames[1].placement_cluster_id).helix_ids).toContain(added.id)
  await picker.selectOption(source.lattice_frames[0].id)
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(2)
  expect(await editor.locator('.sv-cell.occupied').evaluateAll(nodes => nodes.map(n => n.dataset.helixId).sort())).toEqual(beforeIds.sort())
  await editor.waitForTimeout(250) // Finish slice-frame pan/zoom before the review image.
  const visibility = await editor.locator('#sliceview-svg').evaluate(svg => {
    const view = svg.getBoundingClientRect()
    return [...svg.querySelectorAll('.sv-cell.occupied')].map(cell => {
      const box = cell.getBoundingClientRect()
      return box.left >= view.left && box.right <= view.right && box.top >= view.top && box.bottom <= view.bottom
    })
  })
  expect(visibility).toEqual([true, true])
  await editor.screenshot({ path: testInfo.outputPath('frame-editor.png') })
  await picker.selectOption(source.lattice_frames[1].id)
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(3)
  await editor.locator(`.sv-cell[data-helix-id="${added.id}"]`).click()
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(2)
  const remaining = await editor.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design.helices.map(h => h.id))
  expect(remaining.sort()).toEqual(source.helices.map(h => h.id).sort())
  await editor.close()
  expect(errors).toEqual([])
})
