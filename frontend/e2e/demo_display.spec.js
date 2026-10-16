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
test('protected display retains its invitation and automatically rejoins and follows across presentation restarts',async({page,browser},info)=>{
 let screenContext
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 const auth={Authorization:`Bearer ${host.controlToken}`}
 const hostURL=`http://127.0.0.1:${host.server.address().port}`
 const inventory=async()=> (await(await fetch(hostURL+'/host/shares',{headers:auth})).json()).shares
 try {
  await page.goto('/?test=1&doc=__e2e__display')
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover();await page.click('#menu-file-new');await page.fill('#new-design-name','__e2e__Demo Display')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.evaluate(async()=>{await(await import('/src/api/client.js')).createBundle({cells:[[0,0]],lengthBp:42,plane:'XY',name:'__e2e__Demo Display'})})
  await page.evaluate(()=>document.getElementById('menu-file-sharing').click())
  const dialog=page.locator('#share-link-dialog')
  await expect(dialog.locator('[data-display-password]')).toBeVisible()
  const secret=await dialog.locator('[data-display-password]').inputValue()
  const printBefore=await dialog.locator('[data-guest-qr]').innerHTML()
  await dialog.locator('[data-create]').click()
  await expect.poll(async()=> (await inventory()).length,{timeout:30000}).toBe(1)
  let room=(await inventory())[0]
  const invitation=room.qrUrl,url=new URL(invitation),token=new URLSearchParams(url.hash.slice(1)).get('invite')
  const join=async()=>fetch(url.origin+`/meeting/${room.id}/join`,{method:'POST',headers:{Origin:url.origin},body:JSON.stringify({token,entry:'qr',name:'Visitor'})})
  for(let i=0;i<16;i++)expect((await join()).status).toBe(200)
  expect((await join()).status).toBe(202)
  screenContext=await browser.newContext({viewport:{width:1280,height:800}})
  const screen=await screenContext.newPage();screen.on('pageerror',e=>errors.push(e.message))
  const qr=new URL(invitation);qr.searchParams.set('test','1')
  await screen.goto(qr.href)
  await expect(screen.locator('#guest-name')).toBeVisible()
  await expect(screen.locator('input[type=password]')).toHaveCount(0)
  await screen.locator('#guest-name').fill('Demo display')
  await screen.locator('[data-demo-display-setup]').click()
  await screen.locator('#demo-display-password').fill(secret)
  await screen.locator('#join-submit').click()
  await expect.poll(()=>screen.evaluate(()=>!!window.__preparedViewer?.current),{timeout:30000}).toBe(true)
  await expect(screen.locator('[data-follow]')).toHaveText('Demo display · Automatic follow')
  await expect(screen.locator('#guest-admission')).toHaveCount(0)
  await dialog.locator('[data-close]').click()
  await page.locator('.presentation-perspective').click()
  await expect(screen.locator('[data-follow]')).toHaveAttribute('aria-pressed','true')
  await page.locator('[data-admit-guests]').click()
  await expect(screen.locator('[data-follow]')).toHaveAttribute('aria-pressed','true')
  expect((await inventory())[0].admission.displays).toBe(1)
  await screen.screenshot({path:info.outputPath('protected-display.png')})
  await screen.reload()
  await expect(screen.locator('[data-follow]')).toHaveAttribute('aria-pressed','true',{timeout:30000})
  await page.locator('[data-end-presentation]').click()
  await expect(screen.locator('#presentation-waiting')).toBeVisible({timeout:15000})
  await page.evaluate(()=>document.getElementById('menu-file-sharing').click())
  expect(await dialog.locator('[data-guest-qr]').innerHTML()).toBe(printBefore)
  await dialog.locator('[data-create]').click()
  await expect.poll(async()=> (await inventory()).length,{timeout:30000}).toBe(1)
  room=(await inventory())[0];expect(room.qrUrl).toBe(invitation);expect(room.displayPassword).toBe(secret)
  await dialog.locator('[data-close]').click();await page.locator('.presentation-perspective').click()
  await expect(screen.locator('[data-follow]')).toHaveAttribute('aria-pressed','true',{timeout:30000})
  await expect(screen.locator('#join')).toBeHidden()
  await screen.screenshot({path:info.outputPath('rejoined-display.png')})
  await screen.locator('[data-demo-display-exit]').click()
  await expect(screen.locator('#join')).toBeVisible({timeout:15000})
  await expect(screen.locator('input[type=password]')).toHaveCount(0)
  await expect.poll(async()=> (await inventory())[0].admission.displays).toBe(0)
  expect(errors).toEqual([])
 } finally {await screenContext?.close()}
})
