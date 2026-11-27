#!/usr/bin/env node
// Run with native Windows Node for the workstation GPU, against an isolated
// test backend. Own browser profile is cleaned in finally. No molecular writes,
// downloads. Caller owns stdout JSON and any explicit NADOC_BENCH_CAPTURE image.
import {chromium} from '../frontend/node_modules/playwright/index.mjs'
const [url='http://localhost:5175',backend='webgl',kind='optical',reference='256']=process.argv.slice(2)
let browser
const watchdog=setTimeout(()=>{void browser?.close()},540000);watchdog.unref()
try{
  browser=await chromium.launch({executablePath:process.env.NADOC_BENCH_BROWSER??(process.platform==='win32'?'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe':undefined),headless:true,args:['--disable-background-timer-throttling']})
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  page.on('console',m=>{if(m.text().startsWith('BUDGET_TRIAL '))process.stderr.write(m.text()+'\n')})
  let blockedWorkspaceSaves=0
  if(kind.startsWith('plasmonic')){
    // Read the existing design through the normal file browser. The isolated
    // Session-cache isolation does not disable workspace autosave. Acknowledge
    // that UI request locally without forwarding any write to the backend.
    await page.route('**/api/design/save-workspace',async route=>{
      blockedWorkspaceSaves++
      await route.fulfill({json:{path:route.request().postDataJSON().path,identity_disposition:'confirmed'}})
    })
    await page.goto(url);await page.waitForSelector('.lib-search-input',{timeout:90000})
    await page.locator('.lib-search-input').first().fill('Plasmonic_test')
    await page.locator('.lib-file-row',{has:page.locator('.lib-row-name:text-is("Plasmonic_test")')}).first().click()
    await page.waitForFunction(()=>{let ready=false;window.__nadocTest?.scene?.traverse(o=>{if(o.name==='backboneSpheres'&&o.count>0)ready=true});return ready&&window.__photoMode},null,{timeout:90000})
    await page.locator('#photo-tab-btn').click();await page.locator('#photo-lighting-enabled').check()
    await page.waitForFunction(async()=>!(await import('/src/scene/geometry_loads.js')).geometryLoads.getState().busy)
  }else{
    await page.route('**/trace-budget-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
    await page.goto(`${url}/trace-budget-check`)
  }
  if(kind==='plasmonic-inspect'){
    await page.waitForTimeout(1000)
    const inspection=await page.evaluate(()=>{
      const meshes=[];window.__nadocTest.scene.traverseVisible(o=>{if(o.isMesh)meshes.push({name:o.name,instances:o.count??1})})
      return {meshes,settings:window.__photoMode.getSettings()}
    })
    if(process.env.NADOC_BENCH_CAPTURE)await page.screenshot({path:process.env.NADOC_BENCH_CAPTURE})
    console.log(JSON.stringify({inspection,blockedWorkspaceSaves,errors}))
  }else{
  const result=await page.evaluate(async({backend,kind,reference})=>{
    const T=await import('/node_modules/three/build/three.module.js')
    const {measureTraceBudget,budgetOpticalScene}=await import('/e2e/helpers/trace_budget_fixture.js')
    let fixture
    if(kind==='plasmonic'){
      const {scene,camera}=window.__nadocTest,mode=window.__photoMode
      mode.setPathTracing(false)
      window.__nadocTest.pauseViewerRenderingForTest()
      const c=camera.clone();c.aspect=1280/720;c.updateProjectionMatrix();c.updateMatrixWorld()
      fixture={scene,camera:c,settings:mode.getSettings(),dispose(){}}
    }else fixture=budgetOpticalScene({instances:kind==='dense'?18000:0})
    const renderer=new T.WebGLRenderer({preserveDrawingBuffer:true});document.body.append(renderer.domElement)
    try{return await measureTraceBudget({...fixture,renderer,backend,referenceSamples:Number(reference),onMeasurement:r=>console.log('BUDGET_TRIAL '+JSON.stringify({samples:r.samples,timesMs:r.timesMs,renderMs:r.diagnostics.render_ms,workerMs:r.diagnostics.worker_ms}))})}
    finally{fixture.dispose();renderer.dispose();renderer.domElement.remove()}
  },{backend,kind,reference})
  if(errors.length)throw new Error(errors.join('\n'))
  console.log(JSON.stringify({...result,scene:kind,blockedWorkspaceSaves}))
  }
}finally{clearTimeout(watchdog);await browser?.close()}
