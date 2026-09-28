import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs/promises'
import path from 'node:path'
import http from 'node:http'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
const execute=promisify(execFile), root=path.resolve(import.meta.dirname,'..'), base=process.env.NADOC_E2E_API_BASE
const frontendPort=Number(process.env.NADOC_SMOKE_FRONTEND_PORT||5174), controlFile=shareControlFile(root,frontendPort)
let host, proxy, ownsControl=false, pid
// Persistent inventory: exclusive local control file (afterAll), temporary tour
// workspace + __e2e__ part/revisions (global teardown), owned viewer (afterEach).
// Guest proxy/host sockets are stopped in afterAll; evidence stays in outputPath.
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST,'physical runtime opt-in')
test.beforeAll(async()=>{
  try{await fs.access(controlFile);throw Error('Refusing to replace existing host control file')}catch(e){if(e.code!=='ENOENT')throw e}
  host=await createPreparedHost({dist:path.join(root,'dist'),persistent:true})
  await new Promise(ok=>host.server.listen(0,'127.0.0.1',ok))
  const hostURL=`http://127.0.0.1:${host.server.address().port}`
  // Real guest SSE/API and Vite development assets, preserving the request origin.
  proxy=http.createServer((req,res)=>{
    const target=new URL(req.url,req.url.startsWith('/meeting/')?hostURL:`http://127.0.0.1:${frontendPort}`)
    const upstream=http.request(target,{method:req.method,headers:req.headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res)})
    upstream.on('error',()=>res.destroy());res.on('close',()=>upstream.destroy());req.pipe(upstream)
  })
  await new Promise(ok=>proxy.listen(0,'127.0.0.1',ok));host.setPublicBase(`http://127.0.0.1:${proxy.address().port}`)
  await fs.writeFile(controlFile,JSON.stringify({url:hostURL,token:host.controlToken}),{mode:0o600,flag:'wx'});ownsControl=true
})
test.afterEach(async({request})=>{const s=await(await request.get(`${base}/api/vr/status`)).json();if(pid&&s.pid===pid)await request.post(`${base}/api/vr/stop`)})
test.afterAll(async()=>{host?.stop();proxy?.closeAllConnections();proxy?.close();if(ownsControl)await fs.unlink(controlFile)})
test('guest sees tracked VR figure, inverse model scale and VR-only visibility toggle',async({page,context,request},info)=>{
  test.setTimeout(240000)
  await page.goto(`/?doc=__e2e__avatar-${process.pid}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover();await page.click('#menu-file-new')
  await page.fill('#new-design-name','__e2e__VR Avatar');await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.evaluate(async()=> (await import('/src/api/client.js')).createBundle({cells:[[0,0]],lengthBp:42,plane:'XY',name:'__e2e__Avatar'}))
  await page.evaluate(()=>document.getElementById('menu-file-sharing').click());await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({timeout:30000})
  const url=new URL(await page.locator('#share-link-dialog [data-link]').inputValue());url.searchParams.set('test','1')
  await page.locator('#share-link-dialog [data-close]').click()
  await page.evaluate(()=>document.getElementById('menu-help-view-vr').click())
  let status
  await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:30000}).toBe(true)
  const guest=await context.newPage(),errors=[];guest.on('pageerror',e=>errors.push(e.message));await guest.goto(url.href)
  await expect(guest.locator('#join-submit')).toBeEnabled();await guest.locator('#guest-name').fill('Avatar guest');await guest.locator('#join-submit').click()
  await expect.poll(()=>guest.evaluate(()=>!!window.__preparedViewer?.current)).toBe(true)
  const read=()=>guest.evaluate(()=>{
    const v=window.__preparedViewer,a=v.runtime.scene.getObjectByName('vr-presenter-avatar');if(!a)return null
    v.runtime.scene.updateMatrixWorld(true)
    const canvas=document.getElementById('canvas'),points=[]
    a.traverse(m=>{if(m.isMesh && m.geometry.type==='CylinderGeometry'){
      const p=m.getWorldPosition(m.position.clone()).project(v.runtime.camera)
      points.push([(p.x+1)*canvas.clientWidth/2,(1-p.y)*canvas.clientHeight/2])
    }})
    return {visible:a.visible,matrix:a.matrix.toArray(),head:a.children[0].position.toArray(),hands:a.children.slice(1,3).map(g=>g.visible?g.position.toArray():null),points}
  })
  let originalScale
  for(const action of ['pose','scale','gesture','off','on']){
    const output=info.outputPath(action)
    const flight=execute('uv',['run','python','-m','tools.vr_workflows.avatar_probe',status.scrywrite_socket,output,action],{cwd:path.resolve(root,'..'),env:process.env,timeout:90000})
    // Attach rejection handling while waiting for the helper's review-ready file.
    let failure;flight.catch(e=>{failure=e})
    try{
      await expect.poll(async()=>{if(failure)throw failure;try{return JSON.parse(await fs.readFile(path.join(output,'ready.json'),'utf8'))}catch{return null}},{timeout:60000}).not.toBeNull()
      await expect.poll(async()=> (await read())?.visible,{timeout:10000}).toBe(action!=='off')
      if(action==='pose'){
        await guest.evaluate(async()=>{
          const THREE=await import('/node_modules/.vite/deps/three.js'),v=window.__preparedViewer
          v.runtime.scene.updateMatrixWorld(true)
          const box=new THREE.Box3().setFromObject(v.current.scene).union(new THREE.Box3().setFromObject(v.runtime.scene.getObjectByName('vr-presenter-avatar')))
          const c=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()).length(),p=c.clone().add(new THREE.Vector3(1,.4,1).normalize().multiplyScalar(size*1.1))
          v.applyCamera({position:p.toArray(),target:c.toArray(),up:[0,1,0],fov:55,near:size/1000,far:size*10,orbitMode:'orbit'})
        })
        const m=(await read()).matrix;originalScale=Math.hypot(...m.slice(0,3))
      }
      if(action==='scale'){
        const m=(await read()).matrix,scale=Math.hypot(...m.slice(0,3))
        expect(scale/originalScale).toBeGreaterThan(.45);expect(scale/originalScale).toBeLessThan(.55)
      }
      await guest.waitForTimeout(250)
      await guest.screenshot({path:info.outputPath(`guest-${action}.png`)})
      await guest.locator('#canvas').screenshot({path:info.outputPath(`canvas-${action}.png`)})
      const observed=await read()
      await fs.writeFile(info.outputPath(`guest-${action}.json`),JSON.stringify(observed,null,2))
      if(action!=='off'){
        const native=await page.evaluate(async()=>{
          const {docHeaders}=await import('/src/shared/doc_id.js')
          return (await(await fetch('/api/vr/presenter-pose',{headers:docHeaders()})).json()).avatar
        })
        expect(native).not.toBeNull()
        observed.matrix.forEach((x,i)=>expect(x).toBeCloseTo(native.trackingToSource[i],3))
        observed.hands.forEach((hand,i)=>hand.forEach((x,j)=>expect(Math.abs(x-native.hands[i].position[j])).toBeLessThan(.02)))
      }
      await execute('uv',['run','python','-m','tools.vr_workflows.avatar_pixels',info.outputPath(''),action],{cwd:path.resolve(root,'..')})
      if(process.env.NADOC_VR_DEMO==='1'){await guest.bringToFront();await guest.waitForTimeout(Number(process.env.NADOC_VR_DEMO_HOLD||3)*1000)}
    }finally{await fs.writeFile(path.join(output,'release'),'');await flight}
  }
  expect(errors).toEqual([])
  await page.evaluate(()=>document.querySelector('#presentation-controls [data-end-presentation]').click())
  await expect(guest.locator('#guest')).toContainText('Session ended')
  await guest.close()
})
