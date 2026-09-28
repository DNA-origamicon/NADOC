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
 await page.goto('/?doc=__e2e__move-tour&scrywrite=transactions')
 await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
 await page.click('#menu-file-new');await page.fill('#new-design-name','__e2e__VR Move '+kind)
 await page.getByRole('button',{name:'Create',exact:true}).click()
 const seed=await paintDesktopVRSeed(page,info)
 // Generated setup through the same public APIs as the desktop. No fixture or
 // existing workspace is opened. The measured operation below uses VR inputs.
 await page.evaluate(async h=>{
  const api=await import('/src/api/client.js')
  await api.createCluster({name:'Movable helix',helix_ids:[h.id],log:true})
  await api.extrudeOverhang({helixId:h.id,bpIndex:0,direction:'FORWARD',isFivePrime:true,neighborRow:0,neighborCol:8,lengthBp:7})
 },seed.helices.find(h=>h.grid_pos[0]===0&&h.grid_pos[1]===7))
 const read=()=>page.evaluate(async()=>{
  const s=(await import('/src/state/store.js')).store.getState()
  return {design:s.currentDesign,geometry:s.currentGeometry}
 })
 const before=await read()
 const cluster=before.design.cluster_transforms.find(c=>c.name==='Movable helix')
 expect(before.geometry.some(n=>n.overhang_id)).toBe(true)
 fs.writeFileSync(info.outputPath('before.json'),JSON.stringify(before))
 await page.locator('#canvas').click({position:{x:30,y:30}});await page.keyboard.press('f')
 await page.locator('.menu-item').filter({hasText:'Help'}).first().hover();await page.click('#menu-help-view-vr')
 let status
 await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:30000}).toBe(true)
 const probe=(mode)=>execFileSync('uv',['run','python','-m','tools.vr_workflows.move_probe',status.scrywrite_socket,info.outputPath(mode),kind,info.outputPath('before.json'),mode],{cwd:path.resolve(process.cwd(),'..'),env:process.env,stdio:'inherit',timeout:180000})
 probe('edit')
 const saved=(await read()).design
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
  expect(saved.nucleotide_transforms).toHaveLength(kind==='base'?1:7)
  for(const t of saved.nucleotide_transforms){expect(Math.hypot(...t.translation)).toBeGreaterThan(.01);expect(Math.hypot(...t.rotation.slice(0,3))).toBeGreaterThan(.01)}
  const selected=JSON.parse(fs.readFileSync(info.outputPath('edit/result.json')))
  if(kind==='base') {
   const t=saved.nucleotide_transforms[0]
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
 const poseByKey=new Map((saved.nucleotide_transforms||[]).map(t=>[JSON.stringify([t.helix_id,t.bp_index,t.direction,t.copy_k??0]),t]))
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
 expect(moved).toBeGreaterThan(0);expect(unchanged).toBeGreaterThan(100)
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
 const reload=await page.context().newPage();await reload.goto('/?doc=__e2e__move-reloaded')
 await reload.evaluate(async file=>(await import('/src/api/client.js')).loadDesign(file),info.outputPath('transformed.nadoc'))
 const restored=await reload.evaluate(async()=>(await import('/src/state/store.js')).store.getState().currentDesign)
 expect(restored.nucleotide_transforms).toEqual(saved.nucleotide_transforms);expect(restored.cluster_transforms).toEqual(saved.cluster_transforms)
 expect(restored.feature_log).toEqual(saved.feature_log)
 await reload.close()
})
