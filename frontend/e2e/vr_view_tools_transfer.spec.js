import {test,expect} from '@playwright/test'
import fs from 'node:fs'

test('display transfer preserves instancing on small and large atomistic designs',async({page},info)=>{
  test.setTimeout(240000)
  await page.goto('/?doc=__e2e__view-transfer')
  await page.waitForFunction(()=>!!window.__nadocScene)
  const results=[]
  for(const [name,cells,lengthBp] of [['small',[[0,0],[0,1]],42],['large',Array.from({length:20},(_,i)=>[0,i]),140]]) {
    await page.evaluate(async({cells,lengthBp,name})=>{
      const api=await import('/src/api/client.js')
      await api.createBundle({cells,lengthBp,plane:'XY',name:'__e2e__View transfer '+name})
    },{cells,lengthBp,name})
    await page.locator('#menu-view-atomistic-vdw').evaluate(b=>b.click())
    await expect.poll(()=>page.evaluate(()=>{
      let n=0;window.__nadocScene.traverseVisible(o=>{if(o.isInstancedMesh)n+=o.count});return n
    }),{timeout:120000}).toBeGreaterThan(name==='small'?2000:100000)
    await page.locator('[data-vt="lengthHeatmap"]').first().evaluate(b=>{if(!b.classList.contains('active'))b.click()})
    const stats=await page.evaluate(async()=>{
      const {captureVRView,encodeVRView}=await import('/src/scene/vr_view_tools.js')
      const start=performance.now(),v=await captureVRView(window.__nadocScene),captured=performance.now()
      const blob=encodeVRView(v,1)
      return {capture_ms:captured-start,encode_ms:performance.now()-captured,bytes:blob.size,
        batches:v.batches.length,instances:v.batches.reduce((n,b)=>n+b.instances.length/20,0),
        shared_vertices:v.batches.reduce((n,b)=>n+b.vertices.length/9,0),
        expanded_vertices:v.batches.reduce((n,b)=>n+b.vertices.length/9*b.instances.length/20,0)}
    })
    expect(stats.instances).toBeGreaterThan(name==='small'?2000:100000)
    expect(stats.shared_vertices).toBeLessThan(stats.expanded_vertices/20)
    expect(stats.bytes).toBeLessThan(50*1024*1024)
    results.push({name,...stats})
    fs.writeFileSync(info.outputPath('transfer-benchmark.json'),JSON.stringify(results,null,2))
    await page.locator('#menu-view-detail-full').evaluate(b=>b.click())
  }
})
