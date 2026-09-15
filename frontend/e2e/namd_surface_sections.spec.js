import {test,expect} from '@playwright/test'
import fs from 'node:fs'
test.use({viewport:{width:1280,height:900},deviceScaleFactor:0.5})
// Only __e2e__surface-sections.nadoc persists; global teardown removes it.
// No job creation or simulation. Screenshots remain in Playwright output.
test('surface options use matching collapsed Settings sections with no orphan parameters',async({page},info)=>{
 test.setTimeout(120000)
 await page.goto('/?doc=__e2e__surface-sections')
 await page.locator('#menu-file-new').evaluate(el=>el.click())
 await page.fill('#new-design-name','__e2e__surface-sections')
 await page.getByRole('button',{name:'Create',exact:true}).click()
 await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign?.metadata?.name)).toBe('__e2e__surface-sections')
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.click('#md-surface-toggle')
 const card=page.locator('#md-surface-body')
 for(const label of ['Hard surface on','Add surface charge','Graphene nanopore','PEG coating','Two-electrode system'])await expect(card.getByLabel(label,{exact:true})).toBeVisible()
 for(const section of ['hard-surface','screening','nanopore','peg','two-electrodes']){
  const details=card.locator(`#md-${section}-settings`)
  await expect(details).not.toHaveAttribute('open','')
  await expect(details.locator('summary')).toHaveText('Settings')
  for(const field of await details.locator('input[type=number],select').all())await expect(field).not.toBeVisible()
 }
 expect(await card.locator('input[type=number],select').evaluateAll(nodes=>nodes.every(n=>n.closest('details.namd-surface-settings')))).toBe(true)
 await page.screenshot({path:info.outputPath('surface-sections-collapsed.png')})
 await card.getByLabel('Hard surface on',{exact:true}).check()
 for(const section of ['hard-surface','screening','nanopore','peg','two-electrodes'])await card.locator(`#md-${section}-settings > summary`).click()
 const mapping={
  'hard-surface':['md-surface-axis','md-surface-offset','md-surface-dna-clearance','md-surface-water-clearance','md-surface-sheet-margin','md-graphene-representation'],
  screening:['md-screening-charge'],
  'two-electrodes':['md-two-electrodes-model','md-two-electrodes-axis','md-two-electrodes-gap','md-two-electrodes-width','md-two-electrodes-depth','md-two-electrodes-charge'],
  peg:['md-peg-shape','md-peg-size_nm','md-peg-density_per_nm2','md-peg-repeat_units'],
  nanopore:['md-surface-material','md-surface-pore-diameter','md-surface-layers','md-surface-layer-spacing'],
 }
 for(const [section,ids] of Object.entries(mapping))for(const id of ids)await expect(card.locator(`#md-${section}-settings #${id}`)).toBeVisible()
 const styles=await card.locator('.namd-surface-option__toggle').evaluateAll(nodes=>nodes.map(n=>{const s=getComputedStyle(n);return [s.fontSize,s.color,s.gap,s.alignItems]}))
 expect(styles.every(s=>JSON.stringify(s)===JSON.stringify(styles[0]))).toBe(true)
 const overflow=await card.evaluate(el=>[...el.querySelectorAll('input,select,summary')].filter(n=>{const r=n.getBoundingClientRect(),b=el.getBoundingClientRect();return r.width>0 && (r.left<b.left-1 || r.right>b.right+1)}).map(n=>n.id))
 expect(overflow).toEqual([])
 expect(await page.evaluate(()=>!!window.__nadocScene.getObjectByName('Graphene nanopore preview')?.visible)).toBe(true)
 await page.check('#md-surface-enable')
 await page.fill('#md-surface-pore-diameter','4')
 await expect.poll(()=>page.evaluate(()=>window.__nadocScene.getObjectByName('Graphene nanopore preview')?.geometry.parameters.shapes.holes.length)).toBe(1)
 await page.selectOption('#md-surface-axis','+z')
 await page.fill('#md-surface-offset','3')
 const before=await page.evaluate(()=>window.__nadocScene.getObjectByName('Graphene nanopore preview').uuid)
 await page.waitForTimeout(3000)
 expect(await page.evaluate(()=>window.__nadocScene.getObjectByName('Graphene nanopore preview').uuid)).toBe(before)
 await page.uncheck('#md-hard-surface-enable')
 await expect(page.locator('#md-surface-enable')).not.toBeChecked()
 expect(await page.evaluate(()=>!!window.__nadocScene.getObjectByName('Graphene nanopore preview'))).toBe(false)
 await page.check('#md-hard-surface-enable')
 await expect(card.locator('[data-remove-coating]')).not.toBeVisible()
 for(const section of ['hard-surface','screening','nanopore','peg','two-electrodes']){
  await card.locator('details').evaluateAll((nodes,selected)=>{for(const n of nodes)n.open=n.id===`md-${selected}-settings`},section)
  await card.screenshot({path:info.outputPath(`surface-settings-${section}.png`)})
 }

})

// Only __e2e__ document persistence; no job requests or preset writes.
test('two electrodes exclude old surfaces, expose the opposite charge and default the wizard to electrode relaxation',async({page},info)=>{
 await page.goto('/')
 await page.locator('#menu-file-new').evaluate(el=>el.click())
 await page.fill('#new-design-name','__e2e__two-electrodes')
 await page.getByRole('button',{name:'Create',exact:true}).click()
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.click('#md-surface-toggle')
 const pair=page.locator('#md-two-electrodes-enable')
 await page.locator('#md-two-electrodes-settings > summary').click()
 for(const id of ['md-hard-surface-enable','md-screening-enable','md-surface-enable']){
  await page.check(`#${id}`);await pair.check()
  await expect(page.locator(`#${id}`)).not.toBeChecked()
  await page.check(`#${id}`);await expect(pair).not.toBeChecked()
 }
 await pair.check()
 await page.fill('#md-two-electrodes-gap','15')
 await page.fill('#md-two-electrodes-charge','0.025')
 await expect(page.locator('#md-two-electrodes-counter')).toHaveText('-0.0250 C/m²')
 await expect(page.locator('#md-two-electrodes-settings [role=status]')).toContainText('Electrode relaxation')
 const posted=[];page.on('request',r=>{if(r.method()==='POST' && /\/md\/jobs(?:\?|$)/.test(r.url()))posted.push(r.url())})
 await page.click('#md-jobs-new-btn')
 await expect(page.getByRole('dialog')).toBeVisible()
 await page.getByRole('tab',{name:/Protocol & settings/}).click()
 await expect(page.getByRole('dialog')).toContainText('Electrode relaxation')
 await page.keyboard.press('Escape')
 expect(posted).toEqual([])
 expect(await page.evaluate(()=>!!window.__nadocScene.getObjectByName('Graphene nanopore preview')?.visible)).toBe(false)
 const preview=await page.evaluate(()=>{
  const group=window.__nadocScene.getObjectByName('NAMD two-electrode setup preview')
  return {visible:group?.visible,faces:group?.children.filter(c=>c.isMesh).length,
   signs:group?.children.filter(c=>c.userData.chargeSign).map(c=>({sign:c.userData.chargeSign,y:c.position.y}))}
 })
 expect(preview.visible).toBe(true);expect(preview.faces).toBe(2);expect(preview.signs).toHaveLength(32)
 for(const glyph of preview.signs){expect(Math.abs(glyph.y)).toBeGreaterThan(7.5);expect(Math.sign(glyph.y)).toBe(-glyph.sign)}
 await page.locator('.toast button').evaluateAll(nodes=>nodes.forEach(n=>n.click()))
 await page.screenshot({path:info.outputPath('two-electrode-scene.png')})
 await pair.uncheck()
 expect(await page.evaluate(()=>window.__nadocScene.getObjectByName('NAMD two-electrode setup preview')?.visible)).toBe(false)
 await pair.check()
 await page.locator('#md-surface-body').screenshot({path:info.outputPath('two-electrodes.png')})
})

test('small plate surface edits keep the design scene stable',async({page,request})=>{
 test.setTimeout(120000)
 const fixture=new URL('../../workspace/small_plate.nadoc',import.meta.url)
 test.skip(!fs.existsSync(fixture),'Requires small_plate.nadoc')
 await page.goto('/?doc=__e2e__surface-preview')
 await page.waitForFunction(()=>window.__nadocTest)
 await page.evaluate(async content=>{
  const api=await import('/src/api/client.js')
  await api.importDesign(content)
  document.getElementById('welcome-screen')?.classList.add('hidden')
  document.getElementById('left-panel')?.classList.remove('locked-hidden','hidden')
  document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b=>b.disabled=false)
  window.__leftSidebar?.refresh?.()
 },fs.readFileSync(fixture,'utf8'))
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.click('#md-surface-toggle')
 await page.waitForTimeout(1500)
 const serial=()=>page.evaluate(()=>window.__nadocTest.getDesignRenderer().debugRenderedAudit().rebuild)
 const baseline=await serial()
 await page.check('#md-hard-surface-enable')
 await expect.poll(()=>page.evaluate(()=>!!window.__nadocScene.getObjectByName('Graphene nanopore preview')?.visible)).toBe(true)
 await page.check('#md-surface-enable')
 await page.locator('#md-nanopore-settings > summary').click()
 await page.fill('#md-surface-pore-diameter','3.5')
 await page.waitForTimeout(3500)
 expect(await serial()).toEqual(baseline)
 await page.uncheck('#md-hard-surface-enable')
 await page.waitForTimeout(1500)
 expect(await serial()).toEqual(baseline)
 await page.close()
 await request.delete('/api/documents/__e2e__surface-preview')
})
