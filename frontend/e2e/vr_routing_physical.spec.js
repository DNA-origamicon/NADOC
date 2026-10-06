import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import path from 'node:path'
const execute = promisify(execFile)
const base = process.env.NADOC_E2E_API_BASE
let pid
// Only an isolated __e2e__ document and the viewer launched by this test are changed.
test.afterEach(async ({request}) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})
test('routing popup overlays Tools and can be operated with profiled controller input', async ({page,request},info) => {
  test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
  test.setTimeout(240000)
  await page.goto('/?doc=__e2e__vr-routing-physical&scrywrite=transactions')
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
  await page.click('#menu-file-new');await page.fill('#new-design-name','__e2e__VR Routing Physical')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.evaluate(async () => (await import('/src/api/client.js')).createBundle({cells:[[0,0],[1,0],[0,1],[1,1]],lengthBp:84,plane:'XY',name:'__e2e__Route'}))
  let snapshot
  page.on('request',r=>{if(r.url().endsWith('/api/vr/routing'))snapshot=r.postDataJSON()})
  await page.evaluate(()=>document.getElementById('menu-help-view-vr').click())
  let status
  await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:30000}).toBe(true)
  await expect.poll(()=>snapshot?.roots.length).toBe(11)
  let step=0
  const probe=async id=>execute('uv',['run','python','-m','tools.vr_workflows.routing_probe',status.scrywrite_socket,
    path.resolve(process.env.NADOC_VR_ROUTING_EVIDENCE || info.outputPath('physical'),`${step++}-${id}`),id],{cwd:path.resolve(process.cwd(),'..'),env:process.env,timeout:90000,maxBuffer:1024*1024})
  await probe('setup');await probe('menu-routing-scaffold-ends')
  await expect.poll(()=>snapshot?.title).toBe('Autoscaffold')
  const seamless=snapshot.controls.find(c=>c.label.startsWith('Seamless')).id
  await probe(seamless);await expect.poll(()=>snapshot?.controls.find(c=>c.id===seamless)?.active).toBe(true)
  const before = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.strands)
  await probe(snapshot.controls.find(c=>c.label==='Run').id)
  await expect.poll(()=>snapshot?.controls.some(c=>c.id==='dismiss'&&c.enabled),{timeout:60000}).toBe(true)
  expect(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.strands)).not.toEqual(before)
  await probe('menu-edit-undo')
  await expect.poll(async()=>JSON.stringify(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.strands))).toBe(JSON.stringify(before))
  await probe('dismiss');await expect.poll(()=>snapshot?.title).toBe('')
  await probe('menu-seq-assign-scaffold');await expect.poll(()=>snapshot?.title).toBe('Assign Scaffold Sequence')
  await probe('custom-sequence');await probe('key-a');await probe('key-c');await probe('key-done')
  await expect.poll(()=>snapshot?.controls.find(c=>c.id==='custom-sequence')?.label).toBe('Custom sequence (2 bases)')
  await probe(snapshot.controls.find(c=>c.label==='Cancel').id)
  await expect.poll(()=>snapshot?.title).toBe('')
})
