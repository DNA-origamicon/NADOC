import {test,expect} from '@playwright/test'

test.use({viewport:{width:1280,height:900},deviceScaleFactor:0.5})
test('box card shows calculation and inline failures and applies sizing presets',async({page})=>{
 test.setTimeout(90000)
 page.on('pageerror',error=>console.log('PAGE ERROR',error.stack))
 page.on('console',msg=>{if(msg.type()==='error')console.log(msg.text())})
 let phase='loading',jobs=[]
 const pending=[]
 const answer=route=>{const dims=route.request().postDataJSON().box_mode==='rotation'?[16,17,18]:[12,13,14];return phase==='error'?{warnings:['Box geometry is unavailable.']}:{box_preview:{selected_nm:dims,calculated_nm:dims}}}
 await page.route('**/api/md/protocol-box-preview',async route=>{
  if(phase==='loading')pending.push(route)
  else await route.fulfill({json:answer(route)})
 })
 await page.route('**/api/md/jobs',route=>route.fulfill({json:jobs}))
 const dialogs=[]
 page.on('dialog',async dialog=>{dialogs.push(dialog.message());await dialog.dismiss()})
 await page.goto('/?doc=__e2e__box-feedback')
 await page.locator('#menu-file-new').evaluate(el=>el.click())
 await page.fill('#new-design-name','__e2e__box-feedback')
 await page.getByRole('button',{name:'Create',exact:true}).click()
 await expect(page.locator('#welcome-screen')).not.toBeVisible()
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.locator('#md-surface-toggle').evaluate(el=>{if(document.getElementById('md-surface-body').style.display==='none')el.click()})
 await page.locator('#md-hard-surface-enable').evaluate(el=>{if(!el.checked)el.click()})
 const spinner=page.locator('#md-box-loading'),warning=page.locator('#md-box-warning')
 await expect(spinner).toBeVisible()
 expect(await spinner.evaluate(el=>getComputedStyle(el).animationName)).toBe('md-box-spin')
 phase='error'
 for(const route of pending.splice(0))await route.fulfill({json:answer(route)})
 await expect(spinner).not.toBeVisible()
 await expect(warning).toBeVisible()
 await warning.click()
 await expect(page.locator('#md-box-warnings')).toContainText('Box geometry is unavailable')
 phase='success'
 await page.fill('#md-box-padding','3.5')
 await page.selectOption('#md-box-sizing','bbox')
 await expect(spinner).not.toBeVisible()
 await expect(warning).not.toBeVisible()
 await expect(page.locator('#md-box-sizing')).toHaveValue('bbox')
 await expect(page.locator('#md-box-padding')).toHaveValue('3.5')
 await expect(page.locator('#md-box-x')).toHaveValue('12.000')
 await page.selectOption('#md-box-sizing','rotation')
 await expect(page.locator('#md-box-sizing')).toHaveValue('rotation')
 await expect(page.locator('#md-box-x')).toHaveValue('16.000')
 await expect(page.locator('#md-box-preset')).toHaveCount(0)
 await expect(page.locator('#md-box-apply-preset')).toHaveCount(0)
 await page.selectOption('#md-box-sizing','auto')
 await expect(spinner).not.toBeVisible()
 await expect(page.locator('#md-box-x')).toHaveValue('12.000')
 const surfaceId=await page.evaluate(()=>window.__nadocScene.getObjectByName('Graphene nanopore preview').uuid)
 for(const show of [true,false,true]){
  await page.locator('#md-box-view-details').setChecked(show)
  await expect.poll(()=>page.evaluate(()=>{
   const scene=window.__nadocScene,mesh=scene.getObjectByName('Graphene nanopore preview')
   return {id:mesh?.uuid,surface:mesh?.visible,details:scene.getObjectByName('NAMD box and solvent details').visible}
  })).toEqual({id:surfaceId,surface:true,details:show})
 }
 const pixels=await page.evaluate(()=>{
  const scene=window.__nadocScene,mesh=scene.getObjectByName('Graphene nanopore preview'),t=window.__nadocTest
  scene.getObjectByName('NAMD box and solvent details').traverse(node=>{if(node.material && node.material.depthWrite)throw Error(`${node.name} writes depth`)})
  const on=t.renderedPixelCensus().pixelHash
  mesh.visible=false;const off=t.renderedPixelCensus().pixelHash;mesh.visible=true
  return {on,off}
 })
 expect(pixels.on).not.toBe(pixels.off)
 jobs=[{job_id:'__e2e__failed-box',design_name:'Box test',status:'failed',created_at:1,protocol:'mgh',segments:[],error:'Preparation failed: Final box-size check failed: Box X needs 20 nm. Increase this initial box dimension in wizard tab 2 and prepare again.'}]
 await page.evaluate(async()=>{
  window.__nadocMdPanel.deselectJob()
  const all=document.getElementById('md-jobs-show-all');all.checked=true;all.dispatchEvent(new Event('change'))
  await window.__nadocMdPanel.refresh()
 })
 await expect(warning).toBeVisible()
 await expect(page.locator('#md-box-warnings')).toContainText('Box X needs 20 nm')
 await expect(page.locator('#md-box-warnings')).not.toContainText('tab 2')
 expect(dialogs).toEqual([])
})
