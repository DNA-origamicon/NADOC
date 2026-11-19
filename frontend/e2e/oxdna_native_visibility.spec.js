// Read-only existing part; mocked job/display data in memory. No saved structures
// or simulation jobs. __e2e__ sessions and screenshots use global cleanup.
import {test,expect} from '@playwright/test'
test('Off restores native atoms without overlaying the full representation',async({page},info)=>{
 test.setTimeout(120000)
 const job={job_id:'__e2e__native-visibility',design_source_path:'2hb_1xT.nadoc',design_name:'2hb_1xT',status:'completed',backend:'CPU',run_config:{kind:'relax'},stages:[{name:'3_equil',kind:'equil',status:'done',steps:1000}]}
 let positions=[],atoms=[],xyz=[]
 await page.route(/\/api\/oxdna\/jobs(?:\?.*)?$/,r=>r.fulfill({json:[job]}))
 await page.route('**/api/simulate/jobs**',r=>r.fulfill({json:[{...job,engine:'oxdna',kind:'relax'}]}))
 await page.route(`**/api/oxdna/jobs/${job.job_id}/**`,r=>{
  const endpoint=new URL(r.request().url()).pathname.split('/').at(-1)
  if(endpoint==='display')return r.fulfill({json:{ready:true,stage_name:'3_equil',positions}})
  if(endpoint==='atomistic-model')return r.fulfill({json:{atoms,bonds:[]}})
  if(endpoint==='display-atomistic')return r.fulfill({json:{ready:true,atomistic:xyz}})
  if(endpoint.startsWith('atomistic-display-bundle'))return r.fulfill({status:404,json:{detail:'Use legacy model path'}})
  return r.fulfill({json:{ready:false,active:false}})
 })
 await page.goto('/?doc=__e2e__native-visibility&open=2hb_1xT.nadoc&open-type=design')
 await page.waitForFunction(()=>window.__nadocTest?.store.getState().currentGeometry?.length)
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
 await page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`).click()
 await page.evaluate(()=>window.__nadocTest.setRepresentation('vdw'))
 await expect.poll(()=>page.evaluate(()=>{let count=0;window.__nadocTest.getAtomisticRenderer().visitAtoms(()=>count++);return count})).toBeGreaterThan(0)
 const native=await page.evaluate(()=>{
  const t=window.__nadocTest,atoms=[],xyz=[]
  t.getAtomisticRenderer().visitAtoms((atom,pos)=>{atoms.push({...atom});xyz[3*atom.serial]=pos.x;xyz[3*atom.serial+1]=pos.y;xyz[3*atom.serial+2]=pos.z})
  return {atoms,xyz,positions:t.store.getState().currentGeometry.map(n=>({...n,nx:n.base_normal[0],ny:n.base_normal[1],nz:n.base_normal[2]}))}
 })
 ;({atoms,xyz,positions}=native)
 await expect.poll(()=>page.evaluate(()=>window.__nadocTest.isCGVisible())).toBe(false)
 if(!await page.locator('#oxdna-jobs-display-toggle').isVisible())await page.locator('#oxdna-jobs-viz-toggle').click()
 await page.locator('#oxdna-jobs-display-toggle').check()
 await page.waitForFunction(()=>window.__nadocOxdnaDisplay.isActive())
 await expect.poll(()=>page.evaluate(()=>window.__nadocTest.isCGVisible())).toBe(false)
 await page.locator('#oxdna-jobs-viz-off').click()
 await expect.poll(()=>page.evaluate(()=>window.__nadocOxdnaDisplay.isActive())).toBe(false)
 await expect.poll(()=>page.evaluate(()=>window.__nadocTest.isCGVisible())).toBe(false)
 const after=await page.evaluate(()=>{
  const ar=window.__nadocTest.getAtomisticRenderer();let count=0;ar.visitAtoms(()=>count++)
  return {mode:ar.getMode(),count}
 })
 expect(after).toEqual({mode:'vdw',count:atoms.length})
 if(process.env.NADOC_NATIVE_VISUAL){await page.screenshot({path:info.outputPath('native-atoms-off.png')});console.log('NATIVE_VISUAL',info.outputPath('native-atoms-off.png'));await page.waitForTimeout(45000)}
})
