import {test, expect} from '@playwright/test'
import {execFileSync} from 'node:child_process'
import path from 'node:path'
import {paintDesktopVRSeed} from './helpers/vr_desktop_seed.js'
import {verifyVRDesktopRoundTrip} from './helpers/vr_desktop_roundtrip.js'
import {verifyVRPlacementMapping} from './helpers/vr_placement_mapping.js'
import {demoReview} from './helpers/vr_demo.js'

// One viewer/document across all three modes. Diagnostic, not a noisy cohort trial.
// Isolated workspace, __e2e__ names, global teardown; stop only the owned viewer.
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'requires explicit physical headset run')
let launchedPid
const doc = '__e2e__vr-combined-authoring'
const base = process.env.NADOC_E2E_API_BASE
test.afterEach(async ({request}) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (launchedPid && status.pid === launchedPid) {
    await request.post(`${base}/api/vr/stop`)
    await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`)).json()).running,
      {timeout:20000}).toBe(false)
  }
})
test('desktop seed → VR default → blunt end → freeform → desktop/cadnano', async ({page,request},info) => {
  test.setTimeout(process.env.NADOC_VR_DEMO === '1' ? 600000 : 300000)
  await page.goto(`/?doc=${doc}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name','__e2e__Combined VR authoring')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  const seed = await paintDesktopVRSeed(page,info)
  await demoReview(page,'desktop 6HB before VR')
  await page.locator('.menu-item').filter({hasText:'Help'}).first().hover()
  await page.click('#menu-help-view-vr')
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) launchedPid = status.pid
    return status.running && !!status.scrywrite_socket
  },{timeout:30000}).toBe(true)
  const read = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  const probe = async (name, script, env={}, args=[]) => {
    const report = execFileSync('uv',['run','python',`tools/vr_workflows/${script}.py`,
      status.scrywrite_socket,info.outputPath(name),...args],{
      cwd:path.resolve(process.cwd(),'..'),encoding:'utf8',timeout:process.env.NADOC_VR_DEMO === '1' ? 300000 : 150000,
      env:{...process.env,NADOC_VR_FREEFORM:'0',NADOC_VR_CLEAR_TARGET:'0',...env},
    })
    await info.attach(name,{body:report,contentType:'application/json'})
    return read()
  }
  const planar = await probe('default','native_confirm_probe')
  expect(planar.helices).toHaveLength(12)
  expect(planar.helices.slice(0,6)).toEqual(seed.helices)
  expect(planar.lattice_frames).toEqual(seed.lattice_frames)
  expect(planar.helices.every(h=>h.length_bp===42)).toBe(true)
  expect(planar.helices.slice(6).map(h=>h.grid_pos).sort()).toEqual([[0,0],[0,1],[0,2],[1,0],[1,2],[2,1]])
  const ended = await probe('blunt','native_end_probe',{NADOC_VR_END_ZOOM:'4'})
  expect(ended.helices).toHaveLength(12)
  expect(ended.helices.map(h=>h.grid_pos)).toEqual(planar.helices.map(h=>h.grid_pos))
  expect(ended.lattice_frames).toEqual(planar.lattice_frames)
  expect(ended.cluster_transforms).toEqual(planar.cluster_transforms)
  const changed = ended.helices.filter((h,i)=>h.length_bp!==planar.helices[i].length_bp)
  expect(changed).toHaveLength(1)
  expect(changed[0].length_bp).toBe(63)
  const free = await probe('freeform','native_confirm_probe',{NADOC_VR_FREEFORM:'1',NADOC_VR_CLEAR_TARGET:'1'})
  expect(free.helices).toHaveLength(18)
  expect(free.helices.slice(0,12)).toEqual(ended.helices)
  expect(free.lattice_frames).toHaveLength(2)
  expect(free.lattice_frames[0]).toEqual(seed.lattice_frames[0])
  expect(free.helices.slice(12).every(h=>h.length_bp===42 && h.lattice_frame_id===free.lattice_frames[1].id)).toBe(true)
  expect(verifyVRPlacementMapping(info,'freeform',free).passed).toBe(true)
  const exported = await request.get(`${base}/api/design/export/cadnano`,{headers:{'X-NADOC-Doc':doc}})
  expect(exported.status()).toBe(200)
  const cadnano = await exported.json()
  expect(cadnano.vstrands).toHaveLength(18)
  for (const field of ['scaf','stap']) expect(cadnano.vstrands.map(h=>h[field].filter(b=>b.some(n=>n!==-1)).length).sort((a,b)=>a-b)).toEqual([...Array(17).fill(42),63])
  const undone = await probe('undo','native_confirm_probe',{NADOC_VR_UNDO_EXPECT_AUTHORED:'1'},['undo'])
  expect(undone.helices).toEqual(ended.helices)
  expect(undone.lattice_frames).toEqual(ended.lattice_frames)
  await request.post(`${base}/api/vr/stop`)
  await expect.poll(async ()=>(await (await request.get(`${base}/api/vr/status`)).json()).running,{timeout:20000}).toBe(false)
  await verifyVRDesktopRoundTrip(page,request,info,free,{doc,expectedBases:1554,editCell:[2,6],newCellLength:42})
})
