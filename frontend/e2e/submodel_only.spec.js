import { test, expect } from '@playwright/test'
import fs from 'node:fs'

test('show submodel only hides omitted context and restores it across representations', async ({page},info)=>{
  test.skip(!process.env.NADOC_SOLVENT_REVIEW,'Requires isolated completed submodel')
  test.setTimeout(180000)
  const trial=JSON.parse(fs.readFileSync(process.env.NADOC_SOLVENT_REVIEW,'utf8')).find(t=>t.name==='submodel')
  await page.setViewportSize({width:1600,height:1000})
  await page.route('**/api/library/open-part',async route=>{
    const response=await page.request.post('/api/design/load',{data:{path:trial.source},headers:route.request().headers()});await route.fulfill({response})
  })
  await page.goto(`/?debug=1&doc=__e2e__submodel-only&open=${encodeURIComponent(trial.filename)}`)
  await page.waitForFunction(()=>window.__nadocMdPanel && window.__NADOC_SUBMODEL__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/,{timeout:30000})
  for(const name of ['Close Feature log sidebar','Close Properties sidebar']){const close=page.getByRole('button',{name,exact:true});if(await close.count())await close.first().click()}
  await page.evaluate(()=>window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(async id=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob(id)},trial.job_id)
  await page.locator('#md-box-solvent-toggle').click()
  const toggle=page.locator('#md-submodel-only')
  await expect(toggle).toBeEnabled({timeout:30000})
  const response=await page.request.get(`/api/md/jobs/${trial.job_id}/submodel-membership`)
  expect(response.ok()).toBe(true)
  const membership=await response.json()
  expect(membership.omitted_keys.length).toBeGreaterThan(0)
  await page.locator('#md-jobs-display-toggle').check({force:true})
  await expect(page.locator('#md-jobs-display-status')).toContainText(/Displaying frame/i,{timeout:60000})
  await page.evaluate(()=>window.__nadocTest.setRepresentation('full'))
  const audit=()=>page.evaluate(m=>{
    const omitted=new Set(m.omitted_keys),retained=new Set(m.retained_keys)
    const stats={omittedVisible:0,retainedVisible:0}
    for(const e of window.__nadocTest.getDesignRenderer().getBackboneEntries()){
      const n=e.nuc,copy=e._copy??n.copy_k??0
      const key=`${n.helix_id}:${n.bp_index}:${n.direction}${copy?':'+copy:''}`
      const a=e.instMesh.instanceMatrix.array,j=e.id*16
      const visible=[0,1,2,4,5,6,8,9,10].some(k=>Math.abs(a[j+k])>1e-7) && (e.instMesh._instanceAlpha?.array[e.id]??1)>0
      if(visible && omitted.has(key))stats.omittedVisible++
      if(visible && retained.has(key))stats.retainedVisible++
    }
    return stats
  },membership)
  await expect.poll(async()=>(await audit()).omittedVisible).toBeGreaterThan(0)
  const before=await audit()
  await toggle.check()
  await expect.poll(async()=>(await audit()).omittedVisible).toBe(0)
  expect((await audit()).retainedVisible).toBe(before.retainedVisible)
  await page.waitForTimeout(3000)
  expect((await audit()).omittedVisible).toBe(0)
  await page.evaluate(()=>window.__nadocTest.applyCameraPoseForTest({target:[8,2,15],position:[38,12,42]}))
  await page.screenshot({path:info.outputPath('submodel-only-full.png')})
  console.log('REVIEW_IMAGE',info.outputPath('submodel-only-full.png'))
  await page.waitForTimeout(20000)
  for(const representation of ['vdw','ballstick']){
    await page.evaluate(rep=>window.__nadocTest.setRepresentation(rep),representation)
    await expect.poll(()=>page.evaluate(()=>{let n=0;window.__nadocTest.getAtomisticRenderer().visitAtoms(()=>n++);return n}),{timeout:45000}).toBeGreaterThan(0)
    const result=await page.evaluate(async m=>{
      const {atomBaseKey}=await import('/src/scene/base_ref.js')
      const omitted=new Set(m.omitted_keys),retained=new Set(m.retained_keys)
      const result={omittedVisible:0,retainedVisible:0}
      window.__nadocTest.getAtomisticRenderer().visitAtoms((atom,p,{instMesh,id})=>{
        if((instMesh._instanceAlpha?.array[id]??1)<=0)return
        const key=atomBaseKey(atom)
        if(omitted.has(key))result.omittedVisible++
        if(retained.has(key))result.retainedVisible++
      });return result
    },membership)
    expect(result.omittedVisible).toBe(0);expect(result.retainedVisible).toBeGreaterThan(0)
    await page.screenshot({path:info.outputPath(`submodel-only-${representation}.png`)})
    console.log('REVIEW_IMAGE',info.outputPath(`submodel-only-${representation}.png`))
    await page.waitForTimeout(15000)
  }
  await toggle.uncheck()
  await page.evaluate(()=>window.__nadocTest.setRepresentation('full'))
  await expect.poll(audit).toEqual(before)
  await expect(page.locator('#md-jobs-display-status')).toContainText(/Displaying frame/i,{timeout:60000})
  await page.waitForTimeout(1500)
  await expect.poll(audit).toEqual(before)
  await page.screenshot({path:info.outputPath('context-restored.png')})
  console.log('REVIEW_IMAGE',info.outputPath('context-restored.png'))
  await page.waitForTimeout(15000)
})
