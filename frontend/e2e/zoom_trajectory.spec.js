import { test, expect } from '@playwright/test'
import fs from 'node:fs'

test('zoom follows saved and interpolated NAMD frames in the rendered viewport',async({page},info)=>{
  test.skip(!process.env.NADOC_SOLVENT_REVIEW,'Requires isolated completed submodel')
  test.setTimeout(360000)
  const trial=JSON.parse(fs.readFileSync(process.env.NADOC_SOLVENT_REVIEW,'utf8')).find(t=>t.name==='submodel')
  await page.setViewportSize({width:1600,height:1000})
  await page.route('**/api/library/open-part',async route=>{
    const response=await page.request.post('/api/design/load',{data:{path:trial.source},headers:route.request().headers()});await route.fulfill({response})
  })
  await page.goto(`/?debug=1&doc=__e2e__zoom-trajectory&open=${encodeURIComponent(trial.filename)}`)
  await page.waitForFunction(()=>window.__nadocMdPanel && window.__NADOC_ZOOM_VOLUME__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/,{timeout:30000})
  for(const name of ['Close Feature log sidebar','Close Properties sidebar']){const b=page.getByRole('button',{name,exact:true});if(await b.count())await b.first().click()}
  await page.evaluate(()=>window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(async id=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob(id)},trial.job_id)
  await page.locator('#md-box-solvent-toggle').click()
  await page.locator('#md-jobs-traj-toggle').check({force:true})
  await expect(page.locator('#md-jobs-traj-play')).toBeEnabled({timeout:90000})
  await page.locator('#md-submodel-zoom').click()
  await expect.poll(()=>page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.debug().ready),{timeout:60000}).toBe(true)
  await page.evaluate(()=>window.__nadocTest.applyCameraPoseForTest({target:[8,2,15],position:[38,12,42]}))
  const audit=()=>page.evaluate(()=>{
    const main=new Map(window.__nadocTest.getDesignRenderer().getBackboneEntries().map(e=>[`${e.nuc.helix_id}:${e.nuc.bp_index}:${e.nuc.direction}${e.nuc.copy_k?':'+e.nuc.copy_k:''}`,e.pos.toArray()]))
    const zoom=window.__NADOC_ZOOM_VOLUME__.debug()
    let error=0,count=0
    for(const e of zoom.motionPositions){const p=main.get(e.key);if(p){count++;error=Math.max(error,Math.hypot(...p.map((v,i)=>v-e.position[i])))}}
    return {error,count,positions:zoom.motionPositions,revision:zoom.motionRevision,applied:zoom.appliedMotionRevision}
  })
  await expect.poll(async()=>(await audit()).count).toBeGreaterThan(0)
  expect((await audit()).error).toBeLessThan(1e-5)
  await page.locator('#md-jobs-traj-slider').evaluate(el=>{el.value=el.max;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))})
  await page.waitForTimeout(1500)
  expect((await audit()).error).toBeLessThan(1e-5)
  await page.locator('#md-jobs-traj-interpolate').check({force:true})
  await page.locator('#md-jobs-traj-play').click({force:true})
  const samples=[]
  for(let i=0;i<25;i++){await page.waitForTimeout(80);samples.push(await audit())}
  await page.locator('#md-jobs-traj-play').click({force:true})
  expect(Math.max(...samples.map(s=>s.error))).toBeLessThan(1e-5)
  expect(new Set(samples.map(s=>s.revision)).size).toBeGreaterThan(5)
  expect(new Set(samples.map(s=>JSON.stringify(s.positions))).size).toBeGreaterThan(5)
  expect(samples.every(s=>s.revision===s.applied)).toBe(true)
  await page.screenshot({path:info.outputPath('zoom-smooth-trajectory.png')})
  console.log('ZOOM_SYNC',JSON.stringify({samples:samples.length,maxError:Math.max(...samples.map(s=>s.error)),revisions:new Set(samples.map(s=>s.revision)).size,bases:samples[0].count}))
  console.log('REVIEW_IMAGE',info.outputPath('zoom-smooth-trajectory.png'))
  await page.waitForTimeout(20000)
  await page.locator('#md-jobs-traj-interpolate').uncheck({force:true})
  await page.locator('#md-jobs-traj-play').click({force:true})
  await page.waitForTimeout(1200)
  await page.locator('#md-jobs-traj-play').click({force:true})
  expect((await audit()).error).toBeLessThan(1e-5)
  await page.evaluate(()=>window.__nadocTest.setRepresentation('vdw'))
  await expect.poll(()=>page.evaluate(()=>{
    let count=0;window.__nadocTest.getAtomisticRenderer().visitAtoms(()=>count++);return count
  }),{timeout:120000}).toBeGreaterThan(100)
  await page.locator('.zoom-volume-row [data-control="representation"]').selectOption('vdw',{force:true})
  await expect.poll(()=>page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.debug().ready),{timeout:60000}).toBe(true)
  const atomAudit=()=>page.evaluate(async()=>{
    const {zoomLiveAtoms}=await import('/src/scene/zoom_volume_motion.js')
    const main=zoomLiveAtoms(window.__nadocTest.getAtomisticRenderer())
    let count=0,error=0
    for(const [key,p] of window.__NADOC_ZOOM_VOLUME__.debugAtoms()){
      const q=main.get(key);if(!q)continue
      count++;error=Math.max(error,Math.hypot(...p.map((v,i)=>v-q[i])))
    }
    return {count,error,revision:window.__NADOC_ZOOM_VOLUME__.debug().motionRevision}
  })
  await expect.poll(async()=>(await atomAudit()).count,{timeout:60000}).toBeGreaterThan(100)
  await expect.poll(async()=>(await atomAudit()).error,{timeout:60000}).toBeLessThan(1e-5)
  await page.locator('#md-jobs-traj-interpolate').check({force:true})
  await expect(page.locator('#md-jobs-traj-play')).toBeEnabled({timeout:90000})
  await page.locator('#md-jobs-traj-play').click({force:true})
  const atomSamples=[]
  for(let i=0;i<12;i++){await page.waitForTimeout(100);atomSamples.push(await atomAudit())}
  await page.locator('#md-jobs-traj-play').click({force:true})
  expect(Math.max(...atomSamples.map(s=>s.error))).toBeLessThan(1e-5)
  expect(new Set(atomSamples.map(s=>s.revision)).size).toBeGreaterThan(3)
  console.log('ZOOM_ATOM_SYNC',JSON.stringify({samples:atomSamples.length,maxError:Math.max(...atomSamples.map(s=>s.error)),atoms:atomSamples[0].count}))
  await page.screenshot({path:info.outputPath('zoom-atomistic-trajectory.png')})
  console.log('REVIEW_IMAGE',info.outputPath('zoom-atomistic-trajectory.png'))
  await page.waitForTimeout(20000)
  await page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.clear())
  await expect(page.locator('.zoom-volume-inset')).toBeHidden()
})
