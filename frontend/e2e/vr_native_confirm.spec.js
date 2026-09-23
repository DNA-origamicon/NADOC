import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { verifyVRDesktopRoundTrip } from './helpers/vr_desktop_roundtrip.js'
import { paintDesktopVRSeed } from './helpers/vr_desktop_seed.js'
// Physical-runtime integration, explicitly opt-in. Temporary __e2e__ workspace,
// native process stopped in afterEach; runtime cleanup owns launch sidecars.
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'requires explicit physical headset run')
let launchedPid = null
const existingFrame = process.env.NADOC_VR_EXISTING_FRAME === '1'
const freeform = process.env.NADOC_VR_FREEFORM === '1'
const desktopBundle = process.env.NADOC_VR_DESKTOP_BUNDLE === '1'
test.afterEach(async ({ request }) => {
  const base = process.env.NADOC_E2E_API_BASE
  const current = await (await request.get(`${base}/api/vr/status`)).json()
  if (launchedPid && current.pid === launchedPid) {
    await request.post(`${base}/api/vr/stop`)
    await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`)).json()).running, { timeout: 20000 }).toBe(false)
  }
})
test('physical painted Confirm is acknowledged by browser and headset', async ({ page, request }, testInfo) => {
  test.setTimeout(process.env.NADOC_VR_DEMO === '1' ? 600000 : 180000)
  await page.goto('/?doc=__e2e__vr-native-confirm&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR native confirm')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  let initial = null
  if (existingFrame && desktopBundle) {
    initial = await paintDesktopVRSeed(page, testInfo)
  } else if (existingFrame) {
    initial = await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const current = await api.getDesign()
      const result = await api.addFrameExtrusion({ expected_design_id:current.design.id,
        expected_revision:current.revision, cells:[[0,4],[0,5],[0,6],[1,4],[1,6],[2,5]],
        length_bp:42, plane:'XY', translation_nm:[12,-4,8],
        rotation_xyzw:[0,Math.sin(37*Math.PI/360),0,Math.cos(37*Math.PI/360)] })
      return result.design
    })
  }
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  const base = process.env.NADOC_E2E_API_BASE
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) launchedPid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  const report = execFileSync('uv', ['run','python','tools/vr_workflows/native_confirm_probe.py',
    status.scrywrite_socket,testInfo.outputPath('physical')],
    { cwd: path.resolve(process.cwd(),'..'), encoding:'utf8', timeout:150000 })
  await testInfo.attach('native-report', { body:report,contentType:'application/json' })
  const design = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  expect(design.helices).toHaveLength(existingFrame ? 12 : 6)
  expect(design.helices.slice(existingFrame ? 6 : 0).map(h => h.grid_pos).sort()).toEqual([[0,0],[0,1],[0,2],[1,0],[1,2],[2,1]])
  expect(design.helices.every(h => h.length_bp === 42)).toBe(true)
  expect(design.helices.slice(existingFrame ? 6 : 0).every(h => h.lattice_frame_id === design.lattice_frames[freeform ? 1 : 0].id)).toBe(true)
  expect(design.lattice_frames).toHaveLength(freeform ? 2 : 1)
  if (freeform) expect(design.cluster_transforms[1].translation).not.toEqual([0,0,0])
  expect(design.feature_log.filter(f => f.op_kind==='extrude-frame')).toHaveLength((initial?.feature_log?.filter(f => f.op_kind==='extrude-frame').length ?? 0)+1)
  if (initial) {
    expect(design.helices.slice(0,6)).toEqual(initial.helices)
    expect(design.lattice_frames.slice(0,initial.lattice_frames.length)).toEqual(initial.lattice_frames)
    expect(design.cluster_transforms[0].translation).toEqual(initial.cluster_transforms[0].translation)
    expect(design.cluster_transforms[0].rotation).toEqual(initial.cluster_transforms[0].rotation)
  }
  await page.locator('#canvas').click({ position: { x:30, y:30 } })
  await page.keyboard.press('f')
  await page.waitForFunction(() => {
    let visible = false
    window.__nadocTest?.scene?.traverse(o => { if (o.isInstancedMesh && o.count > 0) visible = true })
    return visible
  })
  await page.screenshot({ path:testInfo.outputPath('desktop.png') })
  const exported = await request.get(`${base}/api/design/export/cadnano`,
    { headers: { 'X-NADOC-Doc': '__e2e__vr-native-confirm' } })
  expect(exported.status()).toBe(200)
  const cadnano = await exported.json()
  expect(cadnano.vstrands).toHaveLength(design.helices.length)
  for (const helix of cadnano.vstrands) {
    expect(helix.scaf.filter(b => b.some(n => n !== -1))).toHaveLength(42)
    expect(helix.stap.filter(b => b.some(n => n !== -1))).toHaveLength(42)
  }
  const editor = await page.context().newPage()
  await editor.goto('/cadnano-editor.html?doc=__e2e__vr-native-confirm')
  await expect(editor.locator('.sv-cell.occupied')).toHaveCount(freeform ? 6 : design.helices.length)
  if (freeform) {
    await editor.getByLabel('Lattice frame',{exact:true}).selectOption(design.lattice_frames[1].id)
    await expect(editor.locator('.sv-cell.occupied')).toHaveCount(6)
  }
  await editor.screenshot({ path:testInfo.outputPath('cadnano.png') })
  await editor.close()

  const undoReport = execFileSync('uv', ['run','python','tools/vr_workflows/native_confirm_probe.py',
    status.scrywrite_socket,testInfo.outputPath('undo'),'undo'],
    { cwd: path.resolve(process.cwd(),'..'), encoding:'utf8', timeout:150000,
      env:{ ...process.env, NADOC_VR_UNDO_EXPECT_AUTHORED:existingFrame ? '1' : '0' } })
  await testInfo.attach('undo-report', { body:undoReport,contentType:'application/json' })
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.helices.length)).toBe(existingFrame ? 6 : 0)
  await request.post(`${base}/api/vr/stop`)
  await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`)).json()).running, { timeout:20000 }).toBe(false)
  await verifyVRDesktopRoundTrip(page, request, testInfo, design, freeform ? {editCell:[2,6]} : {})

})
