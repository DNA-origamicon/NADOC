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
test('guest sees native menu pixels, view icons and tool guides',async({page,context,request},info)=>{
  test.setTimeout(300000)
  await page.goto(`/?doc=__e2e__vr-ui-${process.pid}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover();await page.click('#menu-file-new')
  await page.fill('#new-design-name','__e2e__VR UI');await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.evaluate(async()=> (await import('/src/api/client.js')).createBundle({cells:[[0,0]],lengthBp:42,plane:'XY',name:'__e2e__VR UI'}))
  await page.evaluate(()=>document.getElementById('menu-file-sharing').click());await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({timeout:30000})
  const url=new URL(await page.locator('#share-link-dialog [data-link]').inputValue());url.searchParams.set('test','1')
  await page.locator('#share-link-dialog [data-close]').click()
  await page.evaluate(()=>document.getElementById('menu-help-view-vr').click())
  let status
  await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:30000}).toBe(true)
  const guest=await context.newPage(),errors=[];await guest.setViewportSize({width:1920,height:1080});guest.on('pageerror',e=>errors.push(e.message));await guest.goto(url.href)
  await expect(guest.locator('#join-submit')).toBeEnabled();await guest.locator('#guest-name').fill('VR UI guest');await guest.locator('#join-submit').click()
  await expect.poll(()=>guest.evaluate(()=>!!window.__preparedViewer?.current)).toBe(true)
  for(const action of ['left-menu','right-menu','view-tools','closed','wheel','scissors','off','on','desktop']){
    const output=info.outputPath(action)
    const flight=execute('uv',['run','python','-m','tools.vr_workflows.avatar_probe',status.scrywrite_socket,output,action],{cwd:path.resolve(root,'..'),env:process.env,timeout:90000})
    let failure;flight.catch(e=>{failure=e})
    try{
      await expect.poll(async()=>{if(failure)throw failure;try{return JSON.parse(await fs.readFile(path.join(output,'ready.json'),'utf8'))}catch{return null}},{timeout:60000}).not.toBeNull()
      const target=['left-menu','right-menu','view-tools','desktop'].includes(action)?`vr-${action}`:null
      await expect.poll(()=>guest.evaluate(()=>window.__preparedViewer.runtime.scene.getObjectByName('vr-presenter-avatar')?.visible),{timeout:10000}).toBe(action!=='off')
      if(target)await expect.poll(()=>guest.evaluate(name=>!!window.__preparedViewer.runtime.scene.getObjectByName(name)?.visible,target)).toBe(true)
      if(action==='closed')await expect.poll(()=>guest.evaluate(()=>window.__preparedViewer.runtime.scene.getObjectByName('vr-presenter-ui')?.children.filter(c=>c.isMesh).length)).toBe(0)
      if(action!=='off')await guest.evaluate(async target=>{
        const THREE=await import('/node_modules/.vite/deps/three.js'),v=window.__preparedViewer,a=v.runtime.scene.getObjectByName('vr-presenter-avatar')
        v.runtime.scene.updateMatrixWorld(true)
        let c,normal,size
        if(target){const m=a.getObjectByName(target),p=m.geometry.getAttribute('position'),points=[0,1,2,3].map(i=>new THREE.Vector3().fromBufferAttribute(p,i).applyMatrix4(m.matrixWorld))
          c=points.reduce((s,p)=>s.add(p),new THREE.Vector3()).multiplyScalar(.25)
          normal=points[2].clone().sub(points[0]).cross(points[0].clone().sub(points[1])).normalize();size=points[0].distanceTo(points[3])
        }else{const box=new THREE.Box3().setFromObject(a);c=box.getCenter(new THREE.Vector3());size=box.getSize(new THREE.Vector3()).length();normal=new THREE.Vector3(0,0,1).transformDirection(a.matrixWorld)}
        const up=new THREE.Vector3(0,1,0).transformDirection(a.matrixWorld)
        v.applyCamera({position:c.clone().addScaledVector(normal,size*(target?.9:1.2)).toArray(),target:c.toArray(),up:up.toArray(),fov:55,near:size/1000,far:size*20,orbitMode:'orbit'})
      },target)
      await guest.waitForTimeout(500)
      const evidence=await guest.evaluate(target=>{
        const v=window.__preparedViewer,a=v.runtime.scene.getObjectByName('vr-presenter-avatar'),ui=a.getObjectByName('vr-presenter-ui'),canvas=document.getElementById('canvas'),samples=[]
        v.runtime.scene.updateMatrixWorld(true)
        const project=p=>{p.project(v.runtime.camera);return [(p.x+1)*canvas.clientWidth/2,(1-p.y)*canvas.clientHeight/2]}
        if(target){const m=a.getObjectByName(target),image=m.material.map.image,c=document.createElement('canvas');c.width=image.width;c.height=image.height
          const ctx=c.getContext('2d');ctx.drawImage(image,0,0);const data=ctx.getImageData(0,0,c.width,c.height).data,p=m.geometry.getAttribute('position')
          const corner=i=>m.position.clone().fromBufferAttribute(p,i),tl=corner(0),vertical=corner(1).sub(tl),horizontal=corner(2).sub(tl)
          for(let y=8;y<c.height-8;y+=4)for(let x=8;x<c.width-8;x+=4){const i=(y*c.width+x)*4,rgb=[...data.slice(i,i+3)]
            if(data[i+3]>240&&Math.min(...rgb)>145){const point=tl.clone().addScaledVector(horizontal,x/c.width).addScaledVector(vertical,y/c.height).applyMatrix4(m.matrixWorld);samples.push({point:project(point),rgb})}
          }
        }else if(a.visible){const m=ui.children.find(c=>c.isLineSegments),p=m.geometry.getAttribute('position'),color=m.geometry.getAttribute('color')
          for(let i=0;i<p.count;i+=2){const point=m.position.clone().fromBufferAttribute(p,i).add(m.position.clone().fromBufferAttribute(p,i+1)).multiplyScalar(.5).applyMatrix4(m.matrixWorld)
            const rgb=[color.getX(i),color.getY(i),color.getZ(i)].map(x=>Math.round(255*(x<=.0031308?12.92*x:1.055*Math.pow(x,1/2.4)-.055)))
            samples.push({point:project(point),rgb})}
        }
        return {visible:a.visible,panels:ui.children.filter(c=>c.isMesh).map(c=>c.name),samples:samples.filter((_,i)=>i%Math.max(1,Math.floor(samples.length/1000))===0)}
      },target)
      await fs.writeFile(info.outputPath(`guest-${action}.json`),JSON.stringify(evidence))
      await guest.screenshot({path:info.outputPath(`guest-${action}.png`)});await guest.locator('#canvas').screenshot({path:info.outputPath(`canvas-${action}.png`)})
      await execute('uv',['run','python','-m','tools.vr_workflows.presence_ui_pixels',info.outputPath(''),action],{cwd:path.resolve(root,'..')})
      if(process.env.NADOC_VR_DEMO==='1'){await guest.bringToFront();await guest.waitForTimeout(3000)}
    }finally{await fs.writeFile(path.join(output,'release'),'');await flight}
    // Let screenshot/trace work drain before the next measured controller reach.
    await guest.waitForTimeout(750)
  }
  expect(errors).toEqual([])
  await page.evaluate(()=>document.querySelector('#presentation-controls [data-end-presentation]').click())
  await expect(guest.locator('#guest')).toContainText('Session ended');await guest.close()
})
