import {installAuditBrowserTrace, saveAuditBrowserTrace, importAuditDesign} from './helpers/vr_audit_design.js'
import {test,expect} from '@playwright/test'
import * as THREE from 'three'
import {execFileSync} from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import {paintDesktopVRSeed} from './helpers/vr_desktop_seed.js'
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST,'physical runtime opt-in')
const kind=process.env.NADOC_VR_MOVE_TARGET||'base'
const base=process.env.NADOC_E2E_API_BASE
let pid
test.afterEach(async({request})=>{
 const status=await(await request.get(`${base}/api/vr/status`)).json()
 if(pid&&status.pid===pid)await request.post(`${base}/api/vr/stop`)
})
test(`trigger move and rotate ${kind}, undo, save and reopen`,async({page,request},info)=>{
 test.setTimeout(300000)
 // Request real desktop focus, then record actual render counters below;
 // Chromium focus emulation can persist through navigation.
 const cdp=await page.context().newCDPSession(page)
 await cdp.send('Emulation.setFocusEmulationEnabled',{enabled:false})
 await page.goto('/?doc=__e2e__move-tour&scrywrite=transactions'+(process.env.NADOC_VR_MOVE_DESIGN?'&open=move-fixture.nadoc':''))
 if(process.env.NADOC_VR_MOVE_DESIGN){
  await expect.poll(()=>page.evaluate(async()=>(await import('/src/state/store.js')).store.getState().currentDesign?.metadata?.name),{timeout:60000}).toBe('move-fixture')
  await expect(page.locator('#welcome-screen')).toBeHidden()
  // File-open boot removes query options; retain this owned test's live bridge.
  await page.evaluate(()=>{const url=new URL(location.href);url.searchParams.set('scrywrite','transactions');history.replaceState(null,'',url)})
 }else{
 await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
 await page.click('#menu-file-new');await page.fill('#new-design-name','__e2e__VR Move '+kind)
 await page.getByRole('button',{name:'Create',exact:true}).click()
 if (!await importAuditDesign(page,info)) {
 const seed=await paintDesktopVRSeed(page,info)
 // Generated setup through the same public APIs as the desktop. No fixture or
 // existing workspace is opened. The measured operation below uses VR inputs.
 await page.evaluate(async h=>{
  const api=await import('/src/api/client.js')
  await api.createCluster({name:'Movable helix',helix_ids:[h.id],log:true})
  await api.extrudeOverhang({helixId:h.id,bpIndex:0,direction:'FORWARD',isFivePrime:true,neighborRow:0,neighborCol:8,lengthBp:7})
 },seed.helices.find(h=>h.grid_pos[0]===0&&h.grid_pos[1]===7))
 }
 }
 const read=()=>page.evaluate(async()=>{
  const s=(await import('/src/state/store.js')).store.getState()
  const api=await import('/src/api/client.js')
  return {design:{...s.currentDesign,feature_log:(await api._request('GET','/design/feature-log/full')).feature_log},geometry:(await api._request('GET','/design/geometry')).nucleotides}
 })
 await expect.poll(async()=>(await read()).geometry?.length||0,{timeout:60000}).toBeGreaterThan(0)
 const before=await read()
 const cluster=process.env.NADOC_VR_AUDIT_DESIGN?[...before.design.cluster_transforms].sort((a,b)=>b.helix_ids.length-a.helix_ids.length)[0]:before.design.cluster_transforms.find(c=>c.name==='Movable helix')
 if(!process.env.NADOC_VR_MOVE_DESIGN&&!process.env.NADOC_VR_AUDIT_DESIGN)expect(before.geometry.some(n=>n.overhang_id)).toBe(true)
 fs.writeFileSync(info.outputPath('before.json'),JSON.stringify(before))
 await page.locator('#canvas').click({position:{x:30,y:30}});await page.keyboard.press('f')
 await page.locator('.menu-item').filter({hasText:'Help'}).first().hover();await page.click('#menu-help-view-vr')
 let status
 await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:30000}).toBe(true)
 if(process.env.NADOC_VR_AUDIT_DESKTOP_DRAW==='preference-off') {
  await expect(page.locator('#vr-desktop-paused')).toBeVisible()
  await page.click('#vr-desktop-resume')
  await expect(page.locator('#vr-desktop-paused')).toBeHidden()
  const rendered=await page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)).toBeGreaterThan(rendered)
  await page.locator('.menu-item').filter({hasText:'Help'}).first().hover()
  await page.click('#menu-help-vr-desktop-3d')
  await expect(page.locator('#vr-desktop-paused')).toBeVisible()
  await expect(page.locator('#menu-help-vr-desktop-3d')).toHaveAttribute('aria-pressed','false')
  await page.locator('#menu-bar .menu-title').click()
  await expect(page.locator('#menu-help-vr-desktop-3d')).toBeHidden()
  expect(await page.evaluate(()=>{
   const e=document.getElementById('vr-desktop-paused'),r=e.getBoundingClientRect()
   return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&
     [r.left+12,r.left+r.width/2,r.right-12].every(x=>
       document.elementFromPoint(x,r.top+r.height/2)?.closest('#vr-desktop-paused')===e)
  })).toBe(true)
  fs.writeFileSync(info.outputPath('desktop-paused-layout.json'),JSON.stringify(await page.evaluate(()=>{
   const box=id=>{const e=document.getElementById(id);return {rect:e.getBoundingClientRect().toJSON(),text:e.textContent,style:e.getAttribute('style')}}
   return {notice:box('vr-desktop-paused'),canvas:box('canvas-area')}
  })))
  await page.screenshot({path:info.outputPath('desktop-paused.png')})
 }
 const probe=(mode)=>execFileSync('uv',['run','python','-m','tools.vr_workflows.move_probe',status.scrywrite_socket,info.outputPath(mode),kind,info.outputPath('before.json'),mode],{cwd:path.resolve(process.cwd(),'..'),env:process.env,stdio:'inherit',timeout:180000})
 await page.waitForTimeout(1500)
 fs.writeFileSync(info.outputPath('focus-diagnostic.json'),JSON.stringify(await page.evaluate(()=>({testApi:!!window.__nadocTest,focused:document.hasFocus(),active:document.querySelector('#menu-help-view-vr')?.getAttribute('aria-pressed')}))))
 await page.waitForTimeout(500)
 const framesBefore=await page.evaluate(()=>window.__nadocTest.viewerFrameState())
 await page.waitForTimeout(500)
 const framesAfter=await page.evaluate(()=>window.__nadocTest.viewerFrameState())
 fs.writeFileSync(info.outputPath('background-rendering.json'),JSON.stringify({before:framesBefore,after:framesAfter}))
 if(process.env.NADOC_VR_AUDIT_DESKTOP_DRAW==='preference-off') {
  expect(framesAfter.rendered).toBe(framesBefore.rendered)
  expect(framesAfter.callbacks).toBeGreaterThan(framesBefore.callbacks)
 }

 probe('edit')
 const saved=(await read()).design
 const poseKey=t=>JSON.stringify([t.helix_id,t.bp_index,t.direction,t.copy_k??0])
 const priorPoses=new Map((before.design.nucleotide_transforms||[]).map(t=>[poseKey(t),t]))
 const newPoses=(saved.nucleotide_transforms||[]).filter(t=>!priorPoses.has(poseKey(t)))
 for(const t of saved.nucleotide_transforms||[])if(priorPoses.has(poseKey(t)))expect(t).toEqual(priorPoses.get(poseKey(t)))
 expect(saved.feature_log.length).toBe(before.design.feature_log.length+1)
 const entry=saved.feature_log.at(-1)
 expect(saved.feature_log.slice(0,-1)).toEqual(before.design.feature_log)
 if(kind==='cluster') {
  expect(entry).toMatchObject({feature_type:'cluster_op',cluster_id:cluster.id,source:null})
  const pose=saved.cluster_transforms.find(c=>c.id===cluster.id)
  for(const field of ['translation','rotation','pivot'])expect(entry[field]).toEqual(pose[field])
  expect(saved.cluster_transforms.find(c=>c.id===cluster.id).translation).not.toEqual(cluster.translation)
  expect(saved.cluster_transforms.find(c=>c.id===cluster.id).rotation).not.toEqual(cluster.rotation)
 }else{
  expect(entry).toMatchObject({feature_type:'snapshot',op_kind:'nucleotide-transform-batch',
   label:`Move/rotate ${kind==='base'?'1 nucleotide':'7 nucleotides'}`,params:{count:kind==='base'?1:7}})
  expect(entry.design_snapshot_gz_b64).toBeTruthy();expect(entry.post_state_gz_b64).toBeTruthy()
  expect(newPoses).toHaveLength(kind==='base'?1:7)
  for(const t of newPoses){expect(Math.hypot(...t.translation)).toBeGreaterThan(.01);expect(Math.hypot(...t.rotation.slice(0,3))).toBeGreaterThan(.01)}
  const selected=JSON.parse(fs.readFileSync(info.outputPath('edit/result.json')))
  if(kind==='base') {
   const t=newPoses[0]
   expect(JSON.parse(decodeURIComponent(selected.owner_tokens[0]))).toEqual(['base',`${t.helix_id}:${t.bp_index}:${t.direction}`])
  }
  if(kind==='overhang') {
   const overhangId=JSON.parse(decodeURIComponent(selected.owner_tokens[0]))[1]
   const targets=before.geometry.filter(n=>n.overhang_id===overhangId)
   expect(saved.nucleotide_transforms.every(t=>targets.some(n=>n.helix_id===t.helix_id&&n.bp_index===t.bp_index&&n.direction===t.direction))).toBe(true)
  }
 }
 await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
 const featureRow=page.locator(`#feature-log-panel [data-fl-row="${saved.feature_log.length}"]`)
 await expect(featureRow).toBeVisible()
 await expect(featureRow).toContainText(kind==='cluster'?cluster.name:entry.label)
 await page.screenshot({path:info.outputPath('desktop-feature-log.png')})
 const afterGeometry=await page.evaluate(async()=>(await (await import('/src/api/client.js'))._request('GET','/design/geometry')).nucleotides)
 const key=n=>JSON.stringify([n.helix_id,n.bp_index,n.direction,n.copy??0])
 const afterByKey=new Map(afterGeometry.map(n=>[key(n),n]))
 const poseByKey=new Map(newPoses.map(t=>[JSON.stringify([t.helix_id,t.bp_index,t.direction,t.copy_k??0]),t]))
 let moved=0,unchanged=0
 for(const n of before.geometry){
  const after=afterByKey.get(key(n));expect(after).toBeTruthy()
  const pose=poseByKey.get(key(n))
  const inCluster=kind==='cluster'&&cluster.helix_ids.includes(n.helix_id)
  const delta=Math.hypot(...after.backbone_position.map((v,i)=>v-n.backbone_position[i]))
  if(pose){
   const rotation=new THREE.Quaternion(...pose.rotation)
   for(const field of ['backbone_position','base_position']){
    const expected=new THREE.Vector3(...n[field]).sub(new THREE.Vector3(...pose.pivot)).applyQuaternion(rotation).add(new THREE.Vector3(...pose.pivot)).add(new THREE.Vector3(...pose.translation))
    expect(new THREE.Vector3(...after[field]).distanceTo(expected)).toBeLessThan(1e-5)
   }
   moved++
  }else if(inCluster){expect(delta).toBeGreaterThan(.01);moved++}
  else if(!n.overhang_id || kind!=='cluster'){expect(delta).toBeLessThan(1e-5);unchanged++}
 }
 expect(moved).toBeGreaterThan(0)
 if(kind==='cluster'&&process.env.NADOC_VR_AUDIT_DESIGN)expect(unchanged).toBe(before.geometry.filter(n=>!cluster.helix_ids.includes(n.helix_id)).length)
 else expect(unchanged).toBeGreaterThan(100)
 fs.writeFileSync(info.outputPath('scope-check.json'),JSON.stringify({moved,unchanged}))
 fs.writeFileSync(info.outputPath('after.json'),JSON.stringify(await read()))
 const filename=saved.metadata.identity_last_known_path
 await page.evaluate(async file=>(await import('/src/api/client.js')).saveDesignToWorkspace(file),filename)
 const file=path.join(process.env.NADOC_WORKSPACE,filename)
 const onDisk=JSON.parse(fs.readFileSync(file));expect(onDisk.nucleotide_transforms).toEqual(saved.nucleotide_transforms)
 expect(onDisk.feature_log).toEqual(saved.feature_log)
 expect(onDisk.cluster_transforms).toEqual(saved.cluster_transforms)
 fs.copyFileSync(file,info.outputPath('transformed.nadoc'))
 await page.screenshot({path:info.outputPath('desktop-transformed.png')})
 probe('undo')
 await expect.poll(async()=>(await read()).design.nucleotide_transforms).toEqual(before.design.nucleotide_transforms)
 expect((await read()).design.feature_log).toEqual(before.design.feature_log)
 expect((await read()).design.cluster_transforms).toEqual(before.design.cluster_transforms)
 await request.post(`${base}/api/vr/stop`)
 if(process.env.NADOC_VR_AUDIT_DESKTOP_DRAW==='preference-off') {
  await expect(page.locator('#vr-desktop-paused')).toBeHidden()
  const rendered=await page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)).toBeGreaterThan(rendered)
 }
 const reload=await page.context().newPage();await reload.goto('/?doc=__e2e__move-reloaded')
 await reload.evaluate(async file=>(await import('/src/api/client.js')).loadDesign(file),info.outputPath('transformed.nadoc'))
 const restored=await reload.evaluate(async()=>({...(await import('/src/state/store.js')).store.getState().currentDesign,feature_log:(await (await import('/src/api/client.js'))._request('GET','/design/feature-log/full')).feature_log}))
 expect(restored.nucleotide_transforms).toEqual(saved.nucleotide_transforms);expect(restored.cluster_transforms).toEqual(saved.cluster_transforms)
 expect(restored.feature_log).toEqual(saved.feature_log)
 await reload.close()
})

// Optional read-only resource-condition evidence for full-size VR audits.
test.beforeEach(async ({page}) => { await installAuditBrowserTrace(page) })
test.afterEach(async ({page}, info) => { await saveAuditBrowserTrace(page, info) })
