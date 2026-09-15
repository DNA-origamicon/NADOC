import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
// Existing source/job are read-only. In-memory test document only; session cache disabled.
let sourceText
test.beforeEach(()=>{if(process.env.NADOC_SOLVENT_SOURCE)sourceText=readFileSync(process.env.NADOC_SOLVENT_SOURCE,'utf8')})
test.afterEach(()=>{if(sourceText)expect(readFileSync(process.env.NADOC_SOLVENT_SOURCE,'utf8')).toBe(sourceText)})
// Run with the no-supervisor validation config when another backend owns the simulation.
test('ion-only electrode job displays saved solvent frames',async({page},testInfo)=>{
 test.skip(!process.env.NADOC_VALIDATION_JOB,'Provide a retained electrode validation job')
 test.setTimeout(60000)
 const source=process.env.NADOC_SOLVENT_SOURCE
 const original=readFileSync(source,'utf8')
 await page.goto('/?doc=__e2e__electrode-playback')
 await page.waitForSelector('#canvas')
 await page.locator('.lib-file-row',{hasText:'2electrode_solvent_only'}).first().click()
 await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign?.metadata?.name)).toBe('2electrode_solvent_only')
 expect(readFileSync(source,'utf8')).toBe(original)
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.locator(`#simulate-jobs-list [data-job-id="${process.env.NADOC_VALIDATION_JOB}"]`).click()
 await page.check('#md-jobs-display-toggle')
 await page.check('#md-jobs-water-toggle')
 await page.check('#md-jobs-water-scope-box')
 await page.check('#md-jobs-ions-toggle')
 await page.check('#md-jobs-box-toggle')
 await expect.poll(()=>page.evaluate(()=>{
  let count=0;window.__nadocScene.traverse(o=>{if(o.name==='mdSolvent')count+=o.count || 0});return count
 }),{timeout:45000}).toBeGreaterThan(1800)
 await expect(page.locator('#md-jobs-ions-legend')).toContainText('10')
 await page.screenshot({path:testInfo.outputPath('electrode-solvent-playback.png')})
 await page.locator('#canvas').click({position:{x:100,y:100}})
 for(const key of ['F7','F6']){
  await page.keyboard.press(key)
  await expect.poll(()=>page.evaluate(()=>{
   let count=0;window.__nadocScene.traverse(o=>{if(o.name==='mdSolvent'&&o.userData.solventKey==='waterH'&&o.visible)count+=o.count || 0});return count
  }),{timeout:15000}).toBe(3608)
  await expect(page.locator('#md-jobs-display-toggle')).toBeChecked()
  await expect(page.locator('#md-jobs-solvent-status')).toContainText('Solvent on')
  await page.screenshot({path:testInfo.outputPath(`electrode-solvent-${key}.png`)})
 }
 await page.keyboard.press('F4')
 page.on('dialog',dialog=>dialog.accept())
 await page.locator('#md-jobs-traj-interval').fill('5')
 await page.locator('#md-jobs-traj-interval').dispatchEvent('change')
 await page.check('#md-jobs-traj-toggle')
 await expect(page.locator('#md-jobs-traj-status')).toContainText(/frame|ready/i,{timeout:20000})
 await expect(page.locator('#md-jobs-solvent-status')).toContainText('Ions / box ready',{timeout:20000})
 await expect(page.locator('#md-jobs-water-toggle')).toBeDisabled()
 await expect.poll(()=>page.evaluate(()=>{
  let count=0;window.__nadocScene.traverse(o=>{if(o.name==='mdSolvent'&&o.visible)count+=o.count || 0});return count
 })).toBe(20)
 await page.screenshot({path:testInfo.outputPath('electrode-saved-trajectory.png')})
 console.log('solvent',await page.locator('#md-jobs-solvent-status').textContent(),'water',await page.locator('#md-jobs-water-count').textContent())
})

// UI-only failure presentation: callback records intent and never starts a native run.
test('electrode convergence failure offers checkpoint continuation',async({page},testInfo)=>{
 test.skip(!process.env.NADOC_VALIDATION_JOB,'Provide the read-only validation context')
 await page.goto('/?doc=__e2e__electrode-continuation-ui')
 await page.waitForSelector('#canvas')
 await page.evaluate(async()=>{
  const {openVramFixModal}=await import('/src/ui/md_vram_fix.js')
  openVramFixModal({advice:{failure_kind:'electrode_equilibration',remedy:'extend_equilibration',
   error:'Cl profile drift 0.237 exceeds 0.100'},onApply:action=>{window.__extensionIntent=action}})
 })
 const modal=page.getByTestId('vram-fix-modal')
 await expect(modal).toContainText('Cl profile drift 0.237 exceeds 0.100')
 await expect(modal).toContainText('saved checkpoint')
 await page.screenshot({path:testInfo.outputPath('electrode-continuation.png')})
 await modal.getByRole('button',{name:'Continue equilibration (+2.4 ns)',exact:true}).click()
 await expect.poll(()=>page.evaluate(()=>window.__extensionIntent?.type)).toBe('extend_equilibration')
 await expect(modal).toHaveCount(0)
})

// Explicit native validation only. Extension and trajectories are intentional user
// review artifacts; source .nadoc stays read-only. Main backend owns the process.
test('continue the actual retained electrode job through its primary control',async({page},testInfo)=>{
 test.skip(process.env.NADOC_VALIDATE_CONTINUATION!=='1','Explicit guarded native validation only')
 test.setTimeout(90000)
 const id=process.env.NADOC_VALIDATION_JOB
 for(const suffix of ['extend-electrode-equilibration','start']){
  await page.route(`**/api/md/jobs/${id}/${suffix}`,async route=>{
   const response=await page.request.fetch(`http://127.0.0.1:8000/api/md/jobs/${id}/${suffix}`,{
    method:route.request().method(),data:route.request().postData() || undefined,
    headers:{'Content-Type':'application/json'},
   })
   await route.fulfill({response})
  })
 }
 await page.goto('/?doc=__e2e__electrode-native-continuation')
 await page.waitForSelector('#canvas')
 await page.locator('.lib-file-row',{hasText:'2electrode_solvent_only'}).first().click()
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.locator(`#simulate-jobs-list [data-job-id="${id}"]`).click()
 const run=page.getByRole('button',{name:'Continue equilibration…',exact:true})
 await expect(run).toBeEnabled()
 await run.click()
 const modal=page.getByTestId('vram-fix-modal')
 await expect(modal).toContainText('Cl profile drift')
 await page.screenshot({path:testInfo.outputPath('actual-electrode-continuation.png')})
 await modal.getByRole('button',{name:'Continue equilibration (+2.4 ns)',exact:true}).click()
 await expect(modal).toHaveCount(0,{timeout:30000})
 await expect.poll(async()=>{
  const response=await page.request.get(`http://127.0.0.1:8000/api/md/jobs/${id}`)
  return (await response.json()).status
 },{timeout:30000}).toBe('running')
})
