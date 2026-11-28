import {test,expect} from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'

// Browser fixtures use real UI modules and an isolated in-memory store. They
// create no molecular documents, jobs or downloads. The app checks read existing
// documents with backend saves blocked. Session caching is disabled by config;
// global teardown owns isolated bridge credentials, reporter owns browser output.
for (const assembly of [false,true]) {
 test(`EM nanoparticle tab and first-add callout in ${assembly?'assembly':'part'} mode`,async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.setViewportSize({width:1500,height:900})
  await page.route('**/em-sidebar-fixture',route=>route.fulfill({contentType:'text/html',body:`<style>
   #main-area{display:flex;height:95vh}#canvas-area{flex:1;position:relative}#right-panel{display:flex}
   #right-tab-strip{display:flex;flex-direction:column;width:100px} [hidden]{display:none!important}
   </style><div id="main-area"><div id="canvas-area"></div><div id="right-tab-strip"><button id="right-tab-toggle">Toggle</button><button data-tab="properties">Properties</button><button data-tab="assembly" hidden>Assembly</button><button data-tab="em">EM Analysis</button></div><div id="right-panel"><div id="right-tab-content-properties"></div><div id="right-tab-content-assembly"></div><div id="right-tab-content-visualization"></div><div id="right-tab-content-clustering"></div><div id="right-tab-content-overhangs"></div><div id="right-tab-content-em"></div></div></div>`}))
  await page.goto('/em-sidebar-fixture')
  await page.evaluate(async assembly=>{
   const {Scene}=await import('/node_modules/.vite/deps/three.js')
   const {initRightSidebarTabs}=await import('/src/ui/right_sidebar_tabs.js')
   const {initEMAnalysis}=await import('/src/ui/em_analysis.js')
   const {createMockStore}=await import('/src/test-helpers/mock_store.js')
   const state=particles=>assembly
    ? {assemblyActive:true,currentAssembly:{id:'assembly',instances:particles.length?[{id:'instance',source:{type:'inline',design:{nanoparticles:particles}}}]:[]}}
    : {currentDesign:{id:'part',nanoparticles:particles}}
   const store=createMockStore(state([]))
   const rightSidebar=initRightSidebarTabs({document,getAvailableWidth:()=>1000,storage:null})
   rightSidebar.setAssemblyMode(assembly)
   const feature=initEMAnalysis({rightSidebar,scene:new Scene(),store,api:{},nanoparticleSubsystem:{getQuenchingParticles:()=>[]}})
   window.setParticles=present=>store.setState(state(present?[{id:'np',kind:'gold_nanosphere'}]:[]))
   window.disposeEMFixture=()=>{feature.dispose();rightSidebar.dispose()}
  },assembly)
  try {
   const rail=page.locator('#right-tab-strip [data-tab="em"]')
   const intro=page.getByRole('dialog',{name:'EM analysis is available'})
   await expect(rail).not.toBeVisible()
   await page.evaluate(()=>window.setParticles(true))
   await expect(rail).toBeVisible()
   await expect(intro).toBeVisible()
   const tabBox=await rail.boundingBox(),popupBox=await intro.boundingBox()
   expect(Math.abs(tabBox.x-(popupBox.x+popupBox.width)-12)).toBeLessThan(2)
   await rail.click()
   await expect.poll(async()=>{
    const tab=await rail.boundingBox(),hint=await intro.boundingBox()
    return Math.abs(tab.x-(hint.x+hint.width)-12)
   }).toBeLessThan(2)
   await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click()
   await intro.getByRole('button',{name:'OK',exact:true}).click()
   await expect(intro).toHaveCount(0)
   await rail.click()
   await expect(page.locator('#em-analysis-panel [data-run]')).toBeVisible()
   await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click()
   await expect(rail).toBeVisible()
   await rail.click()
   await page.evaluate(()=>window.setParticles(false))
   await expect(rail).not.toBeVisible()
   await expect(page.locator('.sidebar-column[data-panel-type="em"]')).toHaveCount(0)
   await page.evaluate(()=>window.setParticles(true))
   await expect(rail).toBeVisible()
   await expect(intro).toHaveCount(0)
   expect(errors).toEqual([])
  }finally{await page.evaluate(()=>window.disposeEMFixture?.())}
 })
}

for (const [kind,file,hasParticles] of [['part','Plasmonic_test.nadoc',true],['assembly','Ass1.nass',false]]) {
 test(`EM availability in the running ${kind} editor`,async({page})=>{
  const source=new URL(`../../workspace/${file}`,import.meta.url)
  test.skip(!existsSync(source),'Read-only local review document unavailable')
  test.setTimeout(90000)
  const digest=()=>createHash('sha256').update(readFileSync(source)).digest('hex')
  const before=digest(),errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  await page.setViewportSize({width:1500,height:900})
  await page.route('**/api/**',route=>{
   const path=new URL(route.request().url()).pathname
   if(path.startsWith('/api/')&&/save/i.test(path))return route.fulfill({json:{identity_disposition:'confirmed'}})
   return route.continue()
  })
  try {
   await page.goto(`/?doc=__e2e__em-sidebar-${kind}&open=${encodeURIComponent(file)}&open-type=${kind}`)
   await page.waitForFunction(kind=>{
    const state=window.__nadocTest?.store.getState()
    return kind==='assembly'?state?.assemblyActive:!!state?.currentDesign?.nanoparticles?.length
   },kind)
   if(kind==='part')await page.evaluate(()=>window.__nadocTest.setRepresentation('cylinders'))
   const rail=page.locator('#right-tab-strip [data-tab="em"]')
   if(hasParticles){
    await expect(rail).toBeVisible()
    // Free space without changing the document or its saved preferences.
    for(const side of ['left','right']){
     const close=page.locator(`#${side}-panel .sidebar-close:visible`)
     while(await close.count())await close.first().click()
    }
    await rail.click()
    await expect(page.locator('#em-analysis-panel [data-run]')).toBeVisible()
    await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click({timeout:10000})
    await expect(rail).toBeVisible()
    await rail.click()
    await expect(page.locator('#em-analysis-panel')).toBeVisible()
   }else await expect(rail).not.toBeVisible()
   await expect(page.locator('.em-tab-intro')).toHaveCount(0)
   expect(errors).toEqual([])
  }finally{expect(digest()).toBe(before)}
 })
}
