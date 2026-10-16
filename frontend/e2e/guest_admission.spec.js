import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import fs from 'node:fs/promises'
import http from 'node:http'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
const execute = promisify(execFile)
const root = path.resolve(import.meta.dirname, '../..')

// Test-owned local host and guest proxy; no public invitation is created.
let host, proxy, ownsControl=false
const frontendPort=Number(process.env.SCRYWRITE_FRONTEND_PORT||5293)
const controlFile=shareControlFile(path.join(root,'frontend'),frontendPort)
test.beforeAll(async()=>{
  host=await createPreparedHost({dist:path.join(root,'frontend/dist'),persistent:true})
  await new Promise(ok=>host.server.listen(0,'127.0.0.1',ok))
  const hostURL=`http://127.0.0.1:${host.server.address().port}`
  proxy=http.createServer((req,res)=>{
    const target=new URL(req.url,req.url.startsWith('/meeting/')?hostURL:`http://127.0.0.1:${frontendPort}`)
    const upstream=http.request(target,{method:req.method,headers:req.headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res)})
    upstream.on('error',()=>res.destroy());res.on('close',()=>upstream.destroy());req.pipe(upstream)
  })
  await new Promise(ok=>proxy.listen(0,'127.0.0.1',ok));host.setPublicBase(`http://127.0.0.1:${proxy.address().port}`)
  await fs.writeFile(controlFile,JSON.stringify({url:hostURL,token:host.controlToken}),{mode:0o600,flag:'wx'});ownsControl=true
})
test.afterAll(async()=>{await host?.stop();proxy?.closeAllConnections();proxy?.close();if(ownsControl)await fs.unlink(controlFile).catch(e=>{if(e.code!=='ENOENT')throw e})})
test('16-seat presentation queues browsers, rotates oldest guests from desktop and VR, and offers freed places', async ({page,browser,request},info)=>{
 const base=process.env.NADOC_E2E_API_BASE
 let pid, acknowledgements
 const simulated=[]
 const contexts=[],errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 try {
  await page.setViewportSize({width:1600,height:1000});await page.goto('/?test=1&doc=__e2e__admission&scrywrite=transactions')
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover();await page.click('#menu-file-new');await page.fill('#new-design-name','__e2e__Admission')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.evaluate(async()=>{await(await import('/src/api/client.js')).createBundle({cells:[[0,0]],lengthBp:42,plane:'XY',name:'__e2e__Admission'})})
  await page.evaluate(()=>document.getElementById('menu-file-sharing').click());await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({timeout:30000})
  let room
  await expect.poll(async()=>{room=(await(await fetch(`http://127.0.0.1:${host.server.address().port}/host/shares`,{headers:{Authorization:`Bearer ${host.controlToken}`}})).json()).shares[0];return !!room},{timeout:30000}).toBe(true)
  const url=new URL(room.qrUrl);url.searchParams.set('test','1')
  const origin=url.origin,endpoint=origin+`/meeting/${room.id}`,token=new URLSearchParams(url.hash.slice(1)).get('invite')
  const enter=async name=>{const res=await fetch(endpoint+'/join',{method:'POST',headers:{Origin:origin},body:JSON.stringify({token,entry:'qr',name})});return {status:res.status,cookie:res.headers.get('set-cookie')?.split(';')[0],details:await res.json()}}
  const occupants=[];for(let i=0;i<16;i++)occupants.push(await enter('Visitor '+i))
  simulated.push(...occupants)
  acknowledgements=setInterval(()=>{for(const g of simulated)void fetch(endpoint+'/admission',{method:'POST',headers:{Origin:origin,Cookie:g.cookie},body:JSON.stringify({visible:true,active:false})}).catch(()=>{})},10000)
  expect(occupants.every(g=>g.status===200)).toBe(true)
  await page.locator('#share-link-dialog [data-close]').click()
  async function browserGuest(name,mobile=false){
   const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1100,height:800},...(mobile?{isMobile:true,hasTouch:true}:{})});contexts.push(context)
   const guest=await context.newPage();guest.on('pageerror',e=>errors.push(e.message));let scenes=0
   guest.on('request',r=>{if(new URL(r.url()).pathname.endsWith('/scene'))scenes++})
   await guest.goto(url.href);await expect(guest.locator('#join-submit')).toBeEnabled()
   await guest.locator('#guest-name').fill('f.u.c.k');await guest.locator('#join-submit').click();await expect(guest.locator('#join-error')).toContainText('choose another')
   await guest.locator('#guest-name').fill(name);await guest.locator('#join-submit').click();await expect(guest.locator('#guest-admission')).toBeVisible()
   expect(scenes).toBe(0)
   return {guest,scenes:()=>scenes}
  }
  const first=await browserGuest('Browser guest')
  await expect(first.guest.locator('[data-message]')).toContainText('number 1')
  await first.guest.screenshot({path:info.outputPath('waiting-desktop.png')})
  await expect(page.locator('[data-admission-count]')).toContainText('16 active · 1 waiting',{timeout:15000})
  for(const dismiss of await page.locator('.toast button[aria-label="Dismiss"]').all()) await dismiss.click()
  await expect(page.locator('.toast')).toHaveCount(0)
  await page.screenshot({path:info.outputPath('presenter-admission.png')})
  await page.locator('[data-admit-guests]').click()
  await expect.poll(()=>first.guest.evaluate(()=>!!window.__preparedViewer?.current),{timeout:30000}).toBe(true)
  await expect(first.guest.locator('#guest-admission')).toBeHidden()
  expect((await fetch(endpoint+'/scene',{headers:{Cookie:occupants[0].cookie}})).status).toBe(409)
  await first.guest.screenshot({path:info.outputPath('admitted-desktop.png')})
  if(process.env.NADOC_PHYSICAL_VR_TEST){
   await page.locator('.presentation-view-lock').click();await expect(page.locator('.presentation-view-lock')).toHaveAttribute('aria-pressed','true')
   await page.evaluate(()=>document.getElementById('menu-help-view-vr').click());let status
   await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:100000}).toBe(true)
   const profiles=process.env.NADOC_VR_SWEEP_VALIDATE==='1'?['steady_fast','steady_deliberate','variable_fast','variable_deliberate']:['steady_fast']
   for(const [i,preset] of profiles.entries()){
    const next=await enter('Waiting '+preset);expect(next.status).toBe(202);simulated.push(next)
    await execute(path.join(root,'.venv/bin/python'),['-m','tools.vr_workflows.share_probe',status.scrywrite_socket,info.outputPath(preset),'admit'],{cwd:root,env:{...process.env,NADOC_VR_PROFILE:preset},timeout:90000})
    expect((await fetch(endpoint+'/scene',{headers:{Cookie:next.cookie}})).status).toBe(200)
    expect((await fetch(endpoint+'/scene',{headers:{Cookie:occupants[i+1].cookie}})).status).toBe(409)
   }
  }
  const second=await browserGuest('Mobile guest',true)
  await first.guest.locator('[data-leave]').click();await expect(first.guest.locator('[data-message]')).toContainText('You left')
  await expect(second.guest.locator('[data-accept]')).toBeVisible({timeout:15000});expect(second.scenes()).toBe(0)
  await second.guest.screenshot({path:info.outputPath('offered-mobile.png')})
  await second.guest.locator('[data-accept]').click();await expect.poll(()=>second.guest.evaluate(()=>!!window.__preparedViewer?.current),{timeout:30000}).toBe(true)
  await second.guest.screenshot({path:info.outputPath('admitted-mobile.png')})
  await first.guest.locator('[data-rejoin]').click();await expect(first.guest.locator('[data-message]')).toContainText('number 1')
  await page.locator('[data-guest-management] summary').click()
  await page.getByRole('button',{name:'Remove Mobile guest',exact:true}).click()
  await expect(second.guest.locator('[data-message]')).toContainText('presenter released',{timeout:15000})
  expect(errors).toEqual([])
 } finally {
  clearInterval(acknowledgements)
  for(const context of contexts)await context.close()
  if(pid){const status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid===pid)await request.post(`${base}/api/vr/stop`)}
 }
})
