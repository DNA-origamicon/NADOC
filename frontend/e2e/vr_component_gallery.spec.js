import { test, expect } from '@playwright/test'
import { readFile, rm } from 'node:fs/promises'
import path from 'node:path'

// Persists no designs. Native launcher evidence and its owned process are
// removed by afterEach, including failed/timeout runs. Session cache is disabled
// by playwright.smoke.config.js; its global teardown removes bridge credentials.
test.setTimeout(90000)
let owned
const root=path.resolve(import.meta.dirname,'../..')
test.afterEach(async ({request})=>{
  if(!owned)return
  try {
    await request.post(`/api/vr/tours/stop/${owned.id}`,{data:{}})
    await expect.poll(async()=>{
      const response=await request.get('/api/vr/tours/status')
      return (await response.json()).run?.status
    },{timeout:25000}).not.toMatch(/^(running|stopping)$/)
  } finally {
    if(owned.output.startsWith('.development-artifacts/vr-debug-tours/'))await rm(path.join(root,owned.output),{recursive:true,force:true})
    owned=null
  }
})

for(const [component,title] of [['thumbwheel','Ridged thumbwheels'],['button','Button styles'],['card','Cards and lists']]) {
test(`Debug ${component} gallery launches a real desktop without a headset`,async({page,request})=>{
  await page.goto('/?doc=e2e-component-gallery')
  await page.locator('#menu-item-debug > button').click()
  await page.locator('#menu-debug-vr-gallery').hover()
  const group=page.locator('#menu-debug-vr-gallery [data-category=components]')
  await group.hover()
  await expect(group.locator(`[data-start=${component}-gallery][data-mode=demo]`)).toHaveText(title+' VR demo')
  await expect(group.locator(`[data-start=${component}-gallery][data-mode=validate]`)).toBeVisible()
  const launched=page.waitForResponse(r=>r.url().endsWith('/api/vr/tours/start'))
  await group.locator(`[data-start=${component}-gallery][data-mode=desktop]`).click()
  const response=await launched
  expect(response.ok()).toBeTruthy()
  owned=(await response.json()).run
  expect(owned.mode).toBe('desktop')
  const image=path.join(root,owned.output,'evidence/desktop-0.png')
  await expect.poll(async()=>{
    try{return (await readFile(image)).length}catch{return 0}
  },{timeout:45000}).toBeGreaterThan(20000)
  const state=JSON.parse(await readFile(path.join(root,owned.output,'evidence/desktop-0.json'),'utf8'))
  expect(state.active).toBe(true)
  if(component==='thumbwheel')expect(state.wheels.map(w=>w.maximum)).toEqual([10,10,10,100,100,100,1000,1000,1000])
  else {expect(state.component).toBe(component==='card'?'cards':'buttons');expect(state.samples).toHaveLength(6)}
  const status=await request.get('/api/vr/tours/status')
  expect((await status.json()).run.status).toBe('running')
})

}
