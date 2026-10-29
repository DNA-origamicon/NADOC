import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
const root=path.resolve('..'), name='__e2e__close-24hb', file=path.join(root,'workspace','close-review-24hb.nadoc')
test('24hb session close reaches a painted welcome screen',async({page,request})=>{
 test.skip(!fs.existsSync(path.join(root, 'workspace/24hb_0xT.nadoc')), 'Local 24hb performance fixture is unavailable')
 test.setTimeout(120000)
 page.on('pageerror',e=>console.log('PAGE_ERROR',e.message))
 const data=JSON.parse(fs.readFileSync(path.join(root,'workspace/24hb_0xT.nadoc'),'utf8'))
 data.id=name;data.metadata.name=name
 expect(fs.existsSync(file)).toBe(false);fs.writeFileSync(file,JSON.stringify(data))
 try{
  await page.addInitScript(()=>{
   window.__closeAudit={requests:[],tasks:[]}
   const fetch0=window.fetch
   window.fetch=async function(...args){const t=performance.now();try{return await fetch0.apply(this,args)}finally{window.__closeAudit.requests.push({url:String(args[0]),method:args[1]?.method||'GET',start:t,ms:performance.now()-t})}}
   new PerformanceObserver(list=>window.__closeAudit.tasks.push(...list.getEntries().map(x=>({start:x.startTime,ms:x.duration})))).observe({type:'longtask',buffered:true})
   document.addEventListener('click',e=>{if(e.target.closest('#menu-file-close-session'))window.__closeAudit.clicked=performance.now()},true)
  })
  await page.setViewportSize({width:1440,height:1000})
  await page.goto('/?doc='+name)
  await page.locator(`[data-library-path$="close-review-24hb.nadoc"]`).click()
  await expect(page.locator('#welcome-screen')).toBeHidden({timeout:90000})
  await page.waitForFunction(()=>window.__nadocTest?.store?.getState()?.currentGeometry,null,{timeout:10000})
  await page.locator('#menu-bar > .menu-item > button').filter({hasText:/^File$/}).click()
  const cdp=await page.context().newCDPSession(page)
  if(process.env.NADOC_CLOSE_PROFILE){await cdp.send('Profiler.enable');await cdp.send('Profiler.start')}
  await page.locator('#menu-file-close-session').click()
  await expect(page.locator('#welcome-screen')).toBeVisible({timeout:90000})
  const audit=await page.evaluate(async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));const a=window.__closeAudit;return {...a,painted:performance.now(),requests:a.requests.filter(x=>x.start>=a.clicked),tasks:a.tasks.filter(x=>x.start>=a.clicked)}})
  audit.elapsed=audit.painted-audit.clicked
  // Persist optional diagnostics outside the repo; normal runs leave no artifacts.
  const out=process.env.NADOC_CLOSE_OUTPUT_DIR
  if(out) fs.mkdirSync(out,{recursive:true})
  const label=process.env.NADOC_CLOSE_LABEL||'close';if(out) fs.writeFileSync(path.join(out,label+'.json'),JSON.stringify(audit,null,2))
  if(process.env.NADOC_CLOSE_PROFILE){const {profile}=await cdp.send('Profiler.stop');if(out) fs.writeFileSync(path.join(out,label+'.cpuprofile'),JSON.stringify(profile))}
  if(out) await page.screenshot({path:path.join(out,label+'.png')})
  console.log('CLOSE_AUDIT',JSON.stringify(audit))
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign)).toBeNull()
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentGeometry)).toBeNull()
  expect(fs.existsSync(file)).toBe(true)
  const saved = JSON.parse(fs.readFileSync(file, 'utf8'))
  expect(saved.helices.length).toBe(data.helices.length)
  expect(saved.strands.length).toBe(data.strands.length)
  // A paused runtime must resume for the next library open.
  await page.keyboard.press('Escape')
  await page.locator(`[data-library-path$="close-review-24hb.nadoc"]`).click()
  await expect(page.locator('#welcome-screen')).toBeHidden()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentGeometry?.length > 0)
  const frame = await page.evaluate(() => window._viewerFrame)
  await page.waitForFunction(previous => window._viewerFrame > previous, frame)

 }finally{
  await page.close();await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${name}`)
  fs.rmSync(file,{force:true})
  for(const p of ['.session','.nadoc-projects'])fs.rmSync(path.join(root,'workspace',p,name),{recursive:true,force:true})
 }
})
