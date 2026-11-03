import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('annotation edits and repeated oxDNA frames keep native crossover arcs hidden', async ({ page }) => {
  test.setTimeout(120000)
  await page.setViewportSize({width:1600,height:1000})
  const errors=trackConsoleErrors(page)
  await loadScaffoldedPart(page,{doc:'__e2e__annotation-arcs',name:'annotation-arcs'})
  await page.evaluate(async()=>{
    const api=await import('/src/api/client.js')
    const original=window.__nadocTest.store.getState().currentDesign
    const helix=(id,x)=>({id,length_bp:32,axis_start:{x,y:0,z:0},axis_end:{x,y:0,z:10.88}})
    const domain=(id,direction)=>({helix_id:id,start_bp:0,end_bp:31,direction})
    const imported = await api.importDesign(JSON.stringify({id:original.id,metadata:{name:'__e2e__annotation-arcs'},
      helices:[helix('a',0),helix('b',3)], strands:[
        {id:'scaffold',strand_type:'scaffold',domains:[domain('a','FORWARD'),domain('b','REVERSE')]},
        {id:'staple',strand_type:'staple',domains:[domain('b','FORWARD'),domain('a','REVERSE')]},
      ]}))
    if (!imported) throw new Error('Crossover fixture import failed: '+window.__nadocTest.store.getState().lastError)
    await api.getGeometry()
  })
  const arcs=()=>page.evaluate(()=>{
    const g=window.__nadocTest.scene.getObjectByName('xoverArcLines')
    return {visible:g?.visible, vertices:g?.children.reduce((n,o)=>n+(o.geometry?.attributes.position.count??0),0)}
  })
  await expect.poll(async()=>(await arcs()).vertices).toBeGreaterThan(0)
  expect((await arcs()).visible).toBe(true)
  await page.route('**/api/oxdna/jobs/__e2e__annotation-arcs/**',r=>r.fulfill({json:{ready:true}}))
  await page.evaluate(async()=>{
    const t=window.__nadocTest, nucs=t.store.getState().currentGeometry
    const keys=nucs.map(n=>[n.helix_id,n.bp_index,n.direction,n.copy_k??0])
    const frame=nucs.flatMap(n=>[n.backbone_position[0]+4,n.backbone_position[1],n.backbone_position[2],1,0,0,0,0,1])
    await window.__nadocOxdnaDisplay.loadFullTrajectoryPage('__e2e__annotation-arcs',{keys,frames:[frame]})
    await t.setRepresentation('oxdna')
  })
  await expect.poll(async()=>(await arcs()).visible).toBe(false)
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const panel=page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await panel.locator('.anno-add').click()
  const card=panel.locator('.anno-card').first()
  await card.locator('[data-field="text"]').fill('Crossover annotation')
  await page.evaluate(()=>{
    window.__arcLeaks=[];window.__reprRestarts=[]
    window.addEventListener('nadoc:representation-change',e=>{
      window.__reprRestarts.push({representation:e.detail,stack:new Error().stack})
    })
    const sample=()=>{
      if(window.__nadocTest.scene.getObjectByName('xoverArcLines')?.visible) window.__arcLeaks.push(performance.now())
      window.__arcSample=requestAnimationFrame(sample)
    };sample()
    window.__nadocTest.applyCameraPoseForTest({position:[20,-20,20],target:[5.5,0,5.4],up:[0,0,1]})
  })
  for(const text of ['Edited label','Edited again']) {
    await card.locator('[data-field="text"]').fill(text)
    await card.locator('[data-field="highlight"]').check()
    await card.locator('[data-field="highlightType"]').selectOption('silhouette')
    await page.waitForTimeout(250)
  }
  await panel.locator('[data-field="enabled"]').uncheck()
  await page.waitForTimeout(400)
  expect(await page.evaluate(()=>window.__reprRestarts)).toEqual([])
  // An unchanged paused frame used to show native arcs without scheduling a new
  // simulation redraw. Exercise that path independently of annotation filtering.
  await page.evaluate(()=>window.__nadocOxdnaDisplay.reapplyForRepr())
  await page.waitForTimeout(100)
  expect((await arcs()).visible).toBe(false)
  expect(await page.evaluate(()=>{cancelAnimationFrame(window.__arcSample);return window.__arcLeaks})).toEqual([])
  if(process.env.NADOC_E2E_SHOT) await page.screenshot({path:process.env.NADOC_E2E_SHOT})
  // Negative control: native Full should restore the real crossover lines.
  await page.evaluate(()=>window.__nadocTest.setRepresentation('full'))
  await expect.poll(async()=>(await arcs()).visible).toBe(true)
  expect(errors,errors.join('\n')).toEqual([])
})
