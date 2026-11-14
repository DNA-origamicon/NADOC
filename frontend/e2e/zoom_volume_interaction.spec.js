import {test,expect} from '@playwright/test'
import {readFileSync,rmSync,existsSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
const root=fileURLToPath(new URL('../../',import.meta.url)),doc='__e2e__zoom-interaction'
const source=`${root}tests/smoke/smoke_design.nadoc`,session=`${root}workspace/.session/${doc}`
let original
// Existing design is read-only. All metadata/save mutations are intercepted.
// Session caching is disabled; exact afterEach cleanup plus global credentials /
// screenshot cleanup apply on failures as well as success.
test.beforeEach(()=>{original=readFileSync(source);expect(existsSync(session)).toBe(false)})
test.afterEach(async({page,request})=>{try{await page.close();await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${doc}`)}finally{rmSync(session,{recursive:true,force:true});expect(readFileSync(source).equals(original)).toBe(true)}})
test('entry highlight and edge/corner resize work visibly and remain independent',async({page},info)=>{
 test.setTimeout(120000)
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 let saves=[]
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url())
  if(req.method()==='PUT'&&url.pathname.endsWith('/design/zoom-volumes')){
   const b=req.postDataJSON();saves.push(b.volumes)
   return route.fulfill({json:{id:b.document_id,zoom_volumes:b.volumes}})
  }
  if(['POST','PUT','PATCH','DELETE'].includes(req.method())&&!url.pathname.endsWith('/design/load'))return route.fulfill({json:{}})
  return route.continue()
 })
 await page.setViewportSize({width:1600,height:1000})
 await page.goto(`/?debug=1&doc=${doc}`)
 await page.waitForFunction(()=>window.__nadocTest&&window.__NADOC_ZOOM_VOLUME__)
 await page.evaluate(async source=>{
  const api=await import('/src/api/client.js');await api.loadDesign(source);await api.getGeometry()
  document.getElementById('welcome-screen')?.classList.add('hidden')
  for(const id of ['right-panel','right-tab-strip'])document.getElementById(id)?.classList.remove('locked-inactive','hidden')
  document.querySelector('.right-tab-btn[data-tab="visualization"]').click()
  const {createSelectionController}=await import('/src/scene/selection_controller.js')
  const store=window.__nadocTest.store,selection=createSelectionController({store})
  selection.replace([{kind:'strand',id:store.getState().currentDesign.strands[0].id}])
  window.__NADOC_ZOOM_VOLUME__.capture();window.__NADOC_ZOOM_VOLUME__.capture();selection.clear()
 },source)
 const rows=page.locator('.zoom-volume-row'),insets=page.locator('.zoom-volume-inset')
 await expect(insets).toHaveCount(2)
 await expect.poll(()=>page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.debug().entries.every(e=>e.ready))).toBe(true)
 await expect(rows.locator('[data-control=size]')).toHaveCount(0)
 const id=await rows.nth(0).getAttribute('data-zoom-id')
 const second=await insets.nth(1).boundingBox()
 const selectionBefore=await page.evaluate(()=>JSON.stringify(window.__nadocTest.store.getState().selection))
 const before=await page.locator('#canvas').screenshot()
 await rows.nth(0).locator('[data-control=highlight]').check()
 await expect.poll(()=>page.evaluate(id=>{
  const group=window.__nadocTest.scene.getObjectByName(`Zoom highlight ${id}`)
  return group?.visible&&group.children.some(o=>o.isInstancedMesh&&o.count>0)
 },id)).toBe(true)
 await page.waitForTimeout(100)
 const after=await page.locator('#canvas').screenshot()
 expect(before.equals(after)).toBe(false)
 expect(await page.evaluate(()=>JSON.stringify(window.__nadocTest.store.getState().selection))).toBe(selectionBefore)
 await expect(rows.nth(1).locator('[data-control=highlight]')).not.toBeChecked()
 const start=await insets.nth(0).boundingBox(),corner=insets.nth(0).locator('[data-resize-edge=sw]'),p=await corner.boundingBox()
 await page.mouse.move(p.x+p.width/2,p.y+p.height/2);await page.mouse.down();await page.mouse.move(p.x+p.width/2-70,p.y+p.height/2+50,{steps:8});await page.mouse.up()
 await expect.poll(async()=>Math.round((await insets.nth(0).boundingBox()).width)).toBe(Math.round(start.width+70))
 let resized=await insets.nth(0).boundingBox();expect(resized.height).toBeCloseTo(start.height+50,0)
 expect(resized.x+resized.width).toBeCloseTo(start.x+start.width,0)
 const edge=insets.nth(0).locator('[data-resize-edge=e]'),q=await edge.boundingBox()
 await page.mouse.move(q.x+q.width/2,q.y+q.height/2);await page.mouse.down();await page.mouse.move(q.x+q.width/2-40,q.y+q.height/2,{steps:5});await page.mouse.up()
 await expect.poll(async()=>Math.round((await insets.nth(0).boundingBox()).width)).toBe(Math.round(start.width+30))
 expect((await insets.nth(0).boundingBox()).height).toBeCloseTo(resized.height,0)
 expect(await insets.nth(1).boundingBox()).toEqual(second)
 await expect.poll(()=>saves.at(-1)?.[0]?.settings?.width).toBe(start.width+30)
 expect(saves.at(-1)[0].settings.highlight).toBe(true)
 await insets.nth(0).screenshot({path:info.outputPath('resized-inset.png')})
 console.log('ZOOM_INTERACTION',JSON.stringify({start,resized:await insets.nth(0).boundingBox(),highlightPixelChange:!before.equals(after),saved:saves.at(-1)[0].settings}))
 if(process.env.NADOC_ZOOM_INTERACTION_HOLD_MS)await page.waitForTimeout(Number(process.env.NADOC_ZOOM_INTERACTION_HOLD_MS))
 await rows.nth(0).locator('[data-control=delete]').click()
 expect(await page.evaluate(id=>!!window.__nadocTest.scene.getObjectByName(`Zoom highlight ${id}`),id)).toBe(false)
 await expect(insets).toHaveCount(1);expect(errors).toEqual([])
})
