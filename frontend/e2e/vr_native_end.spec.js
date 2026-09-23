import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { verifyVRDesktopRoundTrip } from './helpers/vr_desktop_roundtrip.js'
// Physical-runtime integration, explicitly opt-in. Temporary __e2e__ workspace,
// native process stopped in afterEach; runtime cleanup owns launch sidecars.
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'requires explicit physical headset run')
let launchedPid = null
const existingFrame = process.env.NADOC_VR_EXISTING_FRAME === '1'
const desktopBundle = process.env.NADOC_VR_DESKTOP_BUNDLE === '1'
test.afterEach(async ({ request }) => {
  const base = process.env.NADOC_E2E_API_BASE
  const current = await (await request.get(`${base}/api/vr/status`)).json()
  if (launchedPid && current.pid === launchedPid) {
    await request.post(`${base}/api/vr/stop`)
    await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`)).json()).running, { timeout: 20000 }).toBe(false)
  }
})
test('physical end Confirm preserves canonical cells and refreshes headset', async ({ page, request }, testInfo) => {
  test.setTimeout(180000)
  await page.goto('/?doc=__e2e__vr-native-end&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText:'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name','__e2e__VR native end')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  const initial = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    return (await api.createBundle({ cells:[[0,0],[0,1]],lengthBp:42,plane:'XY',name:'__e2e__End bundle' })).design
  })
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  const base = process.env.NADOC_E2E_API_BASE
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) launchedPid = status.pid
    return status.running && !!status.scrywrite_socket
  },{timeout:30000}).toBe(true)
  const report = execFileSync('uv',['run','python','tools/vr_workflows/native_end_probe.py',
    status.scrywrite_socket,testInfo.outputPath('physical')],
    {cwd:path.resolve(process.cwd(),'..'),encoding:'utf8',timeout:150000})
  await testInfo.attach('native-report',{body:report,contentType:'application/json'})
  const design = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  expect(design.helices.map(h=>h.length_bp).sort((a,b)=>a-b)).toEqual([42,63])
  expect(design.helices.map(h=>h.grid_pos)).toEqual(initial.helices.map(h=>h.grid_pos))
  expect(design.lattice_frames).toEqual(initial.lattice_frames)
  expect(design.cluster_transforms).toEqual(initial.cluster_transforms)
  await page.locator('#canvas').click({position:{x:400,y:300}})
  await page.keyboard.press('f')
  await page.mouse.move(650,400)
  await page.keyboard.down('Shift')
  await page.mouse.down({button:'right'})
  await page.mouse.move(780,440,{steps:10})
  await page.mouse.up({button:'right'})
  await page.keyboard.up('Shift')
  await page.keyboard.press('f')
  await page.mouse.wheel(0,200)
  await page.waitForTimeout(300) // Review camera damping, outside measured input.
  await page.screenshot({path:testInfo.outputPath('desktop.png')})
  const exported = await request.get(`${base}/api/design/export/cadnano`,{headers:{'X-NADOC-Doc':'__e2e__vr-native-end'}})
  expect((await exported.json()).vstrands.map(h=>h.scaf.filter(b=>b.some(n=>n!==-1)).length).sort((a,b)=>a-b)).toEqual([42,63])
  const undoReport = execFileSync('uv',['run','python','tools/vr_workflows/native_confirm_probe.py',
    status.scrywrite_socket,testInfo.outputPath('undo'),'undo'],
    {cwd:path.resolve(process.cwd(),'..'),encoding:'utf8',timeout:150000,
      env:{...process.env,NADOC_VR_UNDO_EXPECT_AUTHORED:'1'}})
  await testInfo.attach('undo-report',{body:undoReport,contentType:'application/json'})
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.helices.map(h=>h.length_bp))).toEqual([42,42])
  await request.post(`${base}/api/vr/stop`)
  await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`)).json()).running,{timeout:20000}).toBe(false)
  await verifyVRDesktopRoundTrip(page,request,testInfo,design,{
    doc:'__e2e__vr-native-end',expectedBases:210,
    newCellLength:design.helices.find(h=>h.grid_pos[0]===0 && h.grid_pos[1]===1).length_bp,
  })

})
