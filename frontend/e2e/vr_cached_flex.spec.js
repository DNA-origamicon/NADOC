import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

// Synthetic saved result through production VR control, MD adapter and display paths.
test('VR displays a cached flex map through the normal control and native packet paths', async ({ page }, info) => {
  await page.route('**/cached-flex-audit', route => route.fulfill({ contentType: 'text/html', body: `
    <div id="simulate-jobs-list"><div data-job-id="saved">Saved result</div></div>
    <div id="md-jobs-viz-body"><label><input type="radio" name="md-viz" value="off" checked>Off</label>
    <label><input type="radio" name="md-viz" value="flex">Flexibility map</label></div>` }))
  await page.goto('/cached-flex-audit')
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { createVRSimulations } = await import('/src/scene/vr_simulations.js')
    const { initOxdnaDisplay, rmsfColorMap } = await import('/src/ui/oxdna_display.js')
    const { mdVizApiAdapter } = await import('/src/ui/md_viz_adapter.js')
    const { captureVRView, encodeVRView } = await import('/src/scene/vr_view_tools.js')
    const n = 6400, scene = new THREE.Scene()
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(.008, 6, 4), new THREE.MeshBasicMaterial({color:0xffffff}), n)
    scene.add(mesh)
    const payload = {ready:true,n_frames:150,min_rmsf:0,max_rmsf:1,mean_rmsf:.5,positions:Array.from({length:n},(_,i)=>({
      helix_id:'h',bp_index:i,direction:'FORWARD',nx:1,ny:0,nz:0,
      backbone_position:[-.85+(i%80)*1.7/79,-.85+Math.floor(i/80)*1.7/79,0],rmsf:(i%80)/79,
    }))}
    let reads=0, displayed, published, updates
    const renderer = {
      applyFemPositions(values) { updates=values; values?.forEach((p,i)=>mesh.setMatrixAt(i,new THREE.Matrix4().makeTranslation(...p.backbone_position)));mesh.instanceMatrix.needsUpdate=true },
      applyScalarColors(colors) { updates.forEach((p,i)=>mesh.setColorAt(i,new THREE.Color(colors[`${p.helix_id}:${p.bp_index}:${p.direction}`])));mesh.instanceColor.needsUpdate=true },
    }
    const display = initOxdnaDisplay({designRenderer:renderer,api:mdVizApiAdapter({getMdRmsf:async()=>{reads++;return payload}})})
    document.querySelector('[value="flex"]').addEventListener('change',()=>{displayed=display.displayRmsf('saved')})
    const bridge = createVRSimulations({jobs:{getSelected:()=>({id:'saved',engine:'namd'})},engineSelector:{getSelected:()=> 'namd'},request:async(_,options)=>{published=JSON.parse(options.body);return {ok:true}}})
    await bridge.publish()
    const start=performance.now()
    await bridge.activate({sequence:1,version:published.version,id:published.controls.find(c=>c.group==='flex').id})
    const shown=await displayed, displayMs=performance.now()-start
    const view=await captureVRView(scene)
    const packet=encodeVRView({...view,schema:6,pixels:new Uint8Array(),width:0,height:0},100)
    const expected=rmsfColorMap(payload).colorByKey
    const color=new THREE.Color();mesh.getColorAt(0,color)
    await display.displayRmsf('saved')
    const heartbeatStart=performance.now()
    for(let i=0;i<20;i++)await bridge.publish()
    return {shown,reads,displayMs,heartbeatMs:performance.now()-heartbeatStart,actual:color.getHex(),expected:expected['h:0:FORWARD'],
      count:updates.length,instances:view.batches.reduce((sum,b)=>sum+b.instances.length/20,0),packet:Array.from(new Uint8Array(await packet.arrayBuffer()))}
  })
  expect(result.shown.ok).toBe(true)
  expect(result.reads).toBe(1)
  expect(result.count).toBe(6400)
  expect(result.instances).toBe(6400)
  expect(result.actual).toBe(result.expected)
  const {packet,...report}=result
  const output=process.env.NADOC_VR_CACHE_AUDIT_DIR || info.outputPath('cached-flex')
  fs.mkdirSync(output,{recursive:true})
  fs.writeFileSync(path.join(output,'flex.nadocvt'),Buffer.from(packet))
  fs.writeFileSync(path.join(output,'delivery.json'),JSON.stringify(report,null,2))
})
