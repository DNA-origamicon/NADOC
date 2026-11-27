import {test,expect} from '@playwright/test'
// Real sidebar/analysis modules, no authored documents, solver jobs or downloads.
// Standard global teardown and cleanup reporter own all browser artifacts.
test('EM rail restores full controls after independently closing simulation options',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/em-sidebar-fixture',route=>route.fulfill({contentType:'text/html',body:`<style>
 #main-area{display:flex;height:95vh}#canvas-area{flex:1;position:relative}#right-panel{display:flex}
 </style><div id="main-area"><div id="canvas-area"></div><div id="right-tab-strip"><button id="right-tab-toggle">Toggle</button><button data-tab="properties">Properties</button><button data-tab="em">EM</button></div><div id="right-panel"><div id="right-tab-content-properties"></div><div id="right-tab-content-em"></div></div></div>`}))
 await page.goto('/em-sidebar-fixture')
 await page.evaluate(async()=>{
  const {Scene}=await import('/node_modules/.vite/deps/three.js')
  const {initRightSidebarTabs}=await import('/src/ui/right_sidebar_tabs.js')
  const {initEMAnalysis}=await import('/src/ui/em_analysis.js')
  const rightSidebar=initRightSidebarTabs({document,getAvailableWidth:()=>1000})
  const feature=initEMAnalysis({rightSidebar,scene:new Scene(),store:{getState:()=>({})},api:{},nanoparticleSubsystem:{getQuenchingParticles:()=>[]}})
  window.disposeEMFixture=()=>{feature.dispose();rightSidebar.dispose()}
  feature.open(true)
 })
 try{
  await expect(page.locator('[data-run]')).not.toBeVisible()
  await expect(page.locator('[data-clear]')).not.toBeVisible()
  await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click()
  await expect(page.locator('.sidebar-column[data-panel-type="properties"]')).toBeVisible()
  await page.locator('#right-tab-strip [data-tab="em"]').click()
  await expect(page.locator('[data-run]')).toBeVisible()
  await expect(page.locator('[data-clear]')).toBeVisible()
  await page.locator('#right-tab-toggle').click()
  await expect(page.locator('#right-panel')).toHaveClass(/hidden/)
  await page.locator('#right-tab-toggle').click()
  await expect(page.locator('[data-run]')).toBeVisible()
  expect(errors).toEqual([])
 }finally{await page.evaluate(()=>window.disposeEMFixture?.())}
})
