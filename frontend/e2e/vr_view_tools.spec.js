import {installAuditBrowserTrace, saveAuditBrowserTrace, importAuditDesign} from './helpers/vr_audit_design.js'
import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
let pid
test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})
test('left quiver tablet exposes supported view tools without Quick Expand in stereo', async ({ page, request }, info) => {
  test.setTimeout(600000)
  if (process.env.NADOC_VR_FRAME_AUDIT === '1') { const cdp = await page.context().newCDPSession(page); await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: false }) }
  await page.goto(`/?doc=__e2e__views-${process.pid}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR Views')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  if (!await importAuditDesign(page, info)) {
  await page.evaluate(async () => (await import('/src/api/client.js')).createBundle({
    cells: [[0,0],[0,1],[0,2]], lengthBp: 42, plane: 'XY', name: '__e2e__Views',
  }))
  await page.evaluate(async()=>{
    const api=await import('/src/api/client.js'),{store}=await import('/src/state/store.js')
    const h=store.getState().currentDesign.helices
    await api.insertLoopSkip(h[0].id,10,1)
    await api.insertLoopSkip(h[0].id,20,-1)
    await api.extrudeOverhang({helixId:h[0].id,bpIndex:0,direction:'REVERSE',isFivePrime:false,neighborRow:0,neighborCol:-1,lengthBp:7})
    const oh=store.getState().currentDesign.overhangs.at(-1)
    await api.patchOverhang(oh.id,{label:'Handle A',sequence:'ACGTACG'})
    await api.createCluster({name:'View displacement',helix_ids:[h[2].id],log:true})
    const cluster=store.getState().currentDesign.cluster_transforms.find(c=>c.name==='View displacement')
    await api.patchCluster(cluster.id,{translation:[-2.5,0,0],commit:true})
    await api.getDesign()
  })
  }
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  const keys=['lengthHeatmap','sequences','undefinedBases','loopSkips','grid','overhangNames','clashes','deform']
  let step=0
  const probe=async action=>{
    const output=info.outputPath(`${step++}-${action}`)
    execFileSync('uv', ['run','python','-m','tools.vr_workflows.view_tools_probe',status.scrywrite_socket,
      output,String(action)],{cwd:path.resolve(process.cwd(),'..'),env:process.env,timeout:90000,stdio:'inherit'})
    const state=JSON.parse(fs.readFileSync(path.join(output,'result.json'),'utf8'))
    expect(state.view_tools.items.map(item=>item.key)).toEqual(keys)
    const flags=await page.evaluate(keys=>keys.reduce((v,k,i)=>v|(document.querySelector(`[data-vt="${k}"]`).classList.contains('active')?1<<(i<7?i:i+1):0),0),keys)
    expect(state.view_tools.flags).toBe(flags)
    await page.screenshot({path:info.outputPath(`desktop-${step}.png`)})
    return state
  }
  await probe('equip')
  for(let i=Number(process.env.NADOC_VR_VIEW_START||0);i<8;i++){
    const before=await page.locator(`[data-vt="${keys[i]}"]`).getAttribute('class')
    await probe(i)
    await expect(page.locator(`[data-vt="${keys[i]}"]`)).not.toHaveAttribute('class',before)
    await probe(i)
  }
  await probe('stow')
})

// Optional read-only resource-condition evidence for full-size VR audits.
test.beforeEach(async ({page}) => { await installAuditBrowserTrace(page) })
test.afterEach(async ({page}, info) => { await saveAuditBrowserTrace(page, info) })
