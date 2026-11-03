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
const frontendPort=Number(process.env.SCRYWRITE_FRONTEND_PORT||process.env.NADOC_SMOKE_FRONTEND_PORT||5293)
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
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
test('VR starts and ends a real presentation while preserving guest invitations', async ({page, request, browser}, info) => {
 const base=process.env.NADOC_E2E_API_BASE
 let pid, guestContext
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 const inventory=async()=> (await(await fetch(`http://127.0.0.1:${host.server.address().port}/host/shares`,{headers:{Authorization:`Bearer ${host.controlToken}`}})).json()).shares
 try {
  await page.setViewportSize({width:1600,height:1000});await page.goto('/?test=1&doc=__e2e__vrshare&scrywrite=transactions')
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover();await page.click('#menu-file-new');await page.fill('#new-design-name','__e2e__VR Share')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.evaluate(async()=>{await(await import('/src/api/client.js')).createBundle({cells:[[0,0]],lengthBp:42,plane:'XY',name:'__e2e__VR Share'})})
  await page.evaluate(()=>document.getElementById('menu-help-view-vr').click());let status
  await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:100000}).toBe(true)
  const profiles=process.env.NADOC_VR_SWEEP_VALIDATE==='1'?['steady_fast','steady_deliberate','variable_fast','variable_deliberate']:[process.env.NADOC_VR_PROFILE||'steady_fast']
  let invitation
  for(const preset of profiles){
   const probe=async action=>execute(path.join(root,'.venv/bin/python'),['-m','tools.vr_workflows.share_probe',status.scrywrite_socket,info.outputPath(preset+'-'+action),action],{cwd:root,env:{...process.env,NADOC_VR_PROFILE:preset},timeout:90000})
   await probe('start')
   await expect.poll(async()=> (await inventory()).length,{timeout:30000}).toBe(1)
   await expect(page.locator('#presentation-controls')).toBeVisible()
   await expect(page.locator('#share-link-dialog')).toBeHidden()
   const room=(await inventory())[0]
   if(invitation)expect(room.qrUrl).toBe(invitation)
   invitation=room.qrUrl
   const url=new URL(room.qrUrl),endpoint=url.origin+`/meeting/${room.id}`
   const token=new URLSearchParams(url.hash.slice(1)).get('invite')
   const guest=await fetch(endpoint+'/join',{method:'POST',headers:{Origin:url.origin},body:JSON.stringify({token,entry:'qr',name:'VR visitor'})})
   expect(guest.status).toBe(200)
   const cookie=guest.headers.get('set-cookie').split(';')[0]
   expect((await fetch(endpoint+'/scene',{headers:{Cookie:cookie}})).status).toBe(200)
   const mobile=preset.includes('variable')
   guestContext = await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1100,height:800},...(mobile?{isMobile:true,hasTouch:true}:{})})
   const guestPage = await guestContext.newPage();guestPage.on('pageerror',e=>errors.push(e.message))
   const guestURL=new URL(room.qrUrl);guestURL.searchParams.set('test','1')
   await guestPage.goto(guestURL.href);await guestPage.locator('#guest-name').fill('Headset follower');await guestPage.locator('#join-submit').click()
   await expect.poll(()=>guestPage.evaluate(()=>!!window.__preparedViewer?.current),{timeout:30000}).toBe(true)
   const independent=await guestPage.evaluate(()=>window.__preparedViewer.captureCamera().position)
   await probe('resume')
   await expect(page.locator('#presentation-controls')).toHaveAttribute('data-perspective-source','headset')
   const state=async()=> (await(await fetch(endpoint+'/status',{headers:{Cookie:cookie}})).json()).presentation
   await expect.poll(async()=> (await state()).camera?.source).toBe('headset')
   await expect(guestPage.locator('[data-follow]')).toBeEnabled()
   expect(await guestPage.evaluate(()=>window.__preparedViewer.captureCamera().position)).toEqual(independent)
   await guestPage.locator('[data-follow]').click()
   await expect.poll(async()=>{
    const expected=(await state()).camera, actual=await guestPage.evaluate(()=>window.__preparedViewer.captureCamera())
    const direction=c=>{const d=c.target.map((v,i)=>v-c.position[i]),n=Math.hypot(...d);return d.map(v=>v/n)}
    const a=direction(actual),b=direction(expected)
    return Math.hypot(...actual.position.map((v,i)=>v-expected.position[i]))/expected.unitsPerMeter < .05 && a.reduce((sum,v,i)=>sum+v*b[i],0)>.995
   },{timeout:20000}).toBe(true)
   await guestPage.locator('#canvas').screenshot({path:info.outputPath(preset+'-guest-fpv.png')})
   await fs.writeFile(info.outputPath(preset+'-camera.json'),JSON.stringify({state:await state(),guest:await guestPage.evaluate(()=>window.__preparedViewer.captureCamera())},null,2))
   // Negative control: removing the actual molecular scene must change rendered pixels.
   await guestPage.evaluate(()=>{window.__preparedViewer.current.scene.visible=false})
   try {await guestPage.locator('#canvas').screenshot({path:info.outputPath(preset+'-guest-no-model.png')})}
   finally {await guestPage.evaluate(()=>{window.__preparedViewer.current.scene.visible=true})}
   await execute(path.join(root,'.venv/bin/python'),['-c',`from PIL import Image, ImageChops
import sys
left=Image.open(sys.argv[1]).convert('RGB');right=Image.open(sys.argv[2]).convert('RGB')
changed=sum(max(p)>30 for p in ImageChops.difference(left,right).getdata())
assert changed>100, f'Molecular scene not visible: {changed} changed pixels'
print(changed)`,info.outputPath(preset+'-guest-fpv.png'),info.outputPath(preset+'-guest-no-model.png')],{cwd:root})
   await probe('pause')
   await expect.poll(async()=> (await state()).presenting).toBe(false)
   // Navigation is still the ordinary opt-out from following.
   await guestPage.locator('#canvas').click({position:{x:200,y:100},timeout:5000})
   await expect(guestPage.locator('[data-follow]')).toHaveAttribute('aria-pressed','false')
   await probe('end')
   await expect.poll(async()=> (await inventory()).length).toBe(0)
   await expect(page.locator('#presentation-controls')).toBeHidden()
   expect((await fetch(endpoint+'/scene',{headers:{Cookie:cookie}})).status).not.toBe(200)
   await guestContext.close();guestContext=null
  }
  expect(errors).toEqual([])
  await page.screenshot({path:info.outputPath('desktop-ended.png')})
 } finally {
  await guestContext?.close().catch(()=>{})
  if(pid){const status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid===pid)await request.post(`${base}/api/vr/stop`)}
 }
})
