import {test,expect} from '@playwright/test'
// Only __e2e__surface-sections.nadoc persists; global teardown removes it.
// No job creation or simulation. Screenshots remain in Playwright output.
test('surface options use matching collapsed Settings sections with no orphan parameters',async({page},info)=>{
 await page.goto('/')
 await page.locator('#menu-file-new').evaluate(el=>el.click())
 await page.fill('#new-design-name','__e2e__surface-sections')
 await page.getByRole('button',{name:'Create',exact:true}).click()
 await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign?.metadata?.name)).toBe('__e2e__surface-sections')
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.click('#md-surface-toggle')
 const card=page.locator('#md-surface-body')
 for(const label of ['Hard surface on','Add surface charge','Graphene nanopore','PEG coating'])await expect(card.getByLabel(label,{exact:true})).toBeVisible()
 for(const section of ['hard-surface','screening','nanopore','peg']){
  const details=card.locator(`#md-${section}-settings`)
  await expect(details).not.toHaveAttribute('open','')
  await expect(details.locator('summary')).toHaveText('Settings')
  for(const field of await details.locator('input[type=number],select').all())await expect(field).not.toBeVisible()
 }
 expect(await card.locator('input[type=number],select').evaluateAll(nodes=>nodes.every(n=>n.closest('details.namd-surface-settings')))).toBe(true)
 await page.screenshot({path:info.outputPath('surface-sections-collapsed.png')})
 await card.getByLabel('Hard surface on',{exact:true}).check()
 for(const section of ['hard-surface','screening','nanopore','peg'])await card.locator(`#md-${section}-settings > summary`).click()
 const mapping={
  'hard-surface':['md-surface-axis','md-surface-offset','md-surface-dna-clearance','md-surface-water-clearance','md-surface-sheet-margin','md-graphene-representation'],
  screening:['md-screening-charge'],
  peg:['md-peg-shape','md-peg-size_nm','md-peg-density_per_nm2','md-peg-repeat_units'],
  nanopore:['md-surface-material','md-surface-pore-diameter','md-surface-layers','md-surface-layer-spacing'],
 }
 for(const [section,ids] of Object.entries(mapping))for(const id of ids)await expect(card.locator(`#md-${section}-settings #${id}`)).toBeVisible()
 const styles=await card.locator('.namd-surface-option__toggle').evaluateAll(nodes=>nodes.map(n=>{const s=getComputedStyle(n);return [s.fontSize,s.color,s.gap,s.alignItems]}))
 expect(styles.every(s=>JSON.stringify(s)===JSON.stringify(styles[0]))).toBe(true)
 const overflow=await card.evaluate(el=>[...el.querySelectorAll('input,select,summary')].filter(n=>{const r=n.getBoundingClientRect(),b=el.getBoundingClientRect();return r.width>0 && (r.left<b.left-1 || r.right>b.right+1)}).map(n=>n.id))
 expect(overflow).toEqual([])
 expect(await page.evaluate(()=>!!window.__nadocScene.getObjectByName('Graphene nanopore preview')?.visible)).toBe(false)
 await expect(card.locator('[data-remove-coating]')).not.toBeVisible()
 for(const section of ['hard-surface','screening','nanopore','peg']){
  await card.locator('details').evaluateAll((nodes,selected)=>{for(const n of nodes)n.open=n.id===`md-${selected}-settings`},section)
  await card.screenshot({path:info.outputPath(`surface-settings-${section}.png`)})
 }

})

// Only __e2e__ document persistence; no job requests or preset writes.
