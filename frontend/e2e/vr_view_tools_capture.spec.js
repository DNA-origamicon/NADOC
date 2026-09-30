import {test,expect} from '@playwright/test'
import fs from 'node:fs'
test('Desktop 2D layouts stay out of VR snapshots',async({page},info)=>{
 test.setTimeout(90000)
  await page.goto(`/?doc=__e2e__view-capture-${process.pid}`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR Views')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
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

 for(const key of ['deform','unfold','cadnano2d']){
   await page.locator(`[data-vt="${key}"]`).first().evaluate(b=>b.click())
   await page.waitForTimeout(1200)
 }
 const invalid=await page.evaluate(async()=>{
   const {captureVRView}=await import('/src/scene/vr_view_tools.js')
   const v=await captureVRView(window.__nadocScene),bad=[]
   const scan=(a,name)=>{const i=a.findIndex(x=>!Number.isFinite(x)||Math.abs(x)>1e9);if(i>=0)bad.push({name,index:i,value:String(a[i]),near:Array.from(a.slice(Math.max(0,i-10),i+15)).map(String)})}
   for(const key of ['triangles','lines','sprites'])scan(v[key],key)
   for(const b of v.batches){scan(b.vertices,b.name+':vertices');scan(b.instances,b.name+':instances')}
   return {bad,flags:v.flags,counts:[v.triangles.length,v.lines.length,v.sprites.length,v.batches.length],atlas:(()=>{const c=document.createElement('canvas');c.width=2048;c.height=2048;c.getContext('2d').putImageData(new ImageData(v.pixels,2048,2048),0,0);return c.toDataURL()})()}
 })
 fs.writeFileSync(info.outputPath('invalid.json'),JSON.stringify(invalid,null,2))
 fs.writeFileSync(info.outputPath('view-panel.png'),Buffer.from(invalid.atlas.split(',')[1],'base64'))
 expect(invalid.bad).toEqual([])
 expect(invalid.flags).toBe(256)
 expect(invalid.counts).toEqual([0,0,0,0])
})

test('old uploads cannot acknowledge a newer tablet click, and failed views remain dismissible',async({page},info)=>{
  await page.goto(`/?doc=__e2e__view-transfer-ack-${process.pid}`)
  await page.waitForFunction(()=>!!window.__nadocScene)
  const report=await page.evaluate(async()=>{
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createVRViewTools}=await import('/src/scene/vr_view_tools.js')
    const doc=document.implementation.createHTMLDocument('Tablet test')
    doc.body.innerHTML='<button data-vt="lengthHeatmap" class="active"></button>'
    const scene=new THREE.Scene(),packets=[],errors=[]
    const original=window.fetch
    let release,started
    const uploading=new Promise(r=>{started=r})
    window.fetch=async(url,options)=>{
      if(url!='/api/vr/view-tools')return original(url,options)
      const data=await options.body.arrayBuffer(),header=Array.from(new Uint32Array(data,8,10))
      packets.push({schema:header[0],flags:header[2],ack:header[9],bytes:data.byteLength})
      if(packets.length===1){started();await new Promise(r=>{release=r})}
      return new Response('{}',{status:200})
    }
    const coordinator=createVRViewTools({scene,doc,getState:()=>({}),onError:message=>errors.push(message)})
    const pause=()=>new Promise(r=>setTimeout(r,1600))
    try {
      await coordinator.publish();await pause()
      const pending=coordinator.publish();await uploading
      coordinator.activate(0,17)
      release();await pending
      await pause();await coordinator.publish()
      const canvas=document.createElement('canvas');canvas.width=3000;canvas.height=10
      scene.add(new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas)})))
      coordinator.activate(0,18);await pause();await coordinator.publish()
      return {packets,errors}
    }finally{coordinator.reset();window.fetch=original}
  })
  fs.writeFileSync(info.outputPath('acknowledgements.json'),JSON.stringify(report,null,2))
  expect(report.packets.map(p=>p.ack)).toEqual([0,17,18])
  expect(report.packets.at(-1).flags).toBe(report.packets[1].flags)
  expect(report.errors).toEqual(['View texture exceeds VR atlas size'])
})
