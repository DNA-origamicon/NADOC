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
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime required')

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
test('native Feature Log edits a saved Sweep and preserves history through undo and redo', async ({ page, context, request }, info) => {
  const base = process.env.NADOC_E2E_API_BASE
  let pid
  const errors=[];page.on('pageerror', e=>errors.push(e.message))
  try {
    await page.setViewportSize({width:1600,height:1000})
    await page.goto('/?test=1&doc=__e2e__vr-sweep-edit&scrywrite=transactions')
    await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
    await page.click('#menu-file-new');await page.fill('#new-design-name','__e2e__VR Sweep Edit')
    await page.getByRole('button',{name:'Create',exact:true}).click()
    await page.evaluate(async()=>{
      const api=await import('/src/api/client.js')
      if(!await api.createSweep({cells:[[0,0],[0,1]],points_nm:[[0,0,0],[4,0,7],[-4,0,14],[0,0,21]],ligate_adjacent:false}))throw Error('fixture failed')
    })
    await page.waitForTimeout(2000)
    const read=()=>page.evaluate(async()=>{
      const api=await import('/src/api/client.js'),{store}=await import('/src/state/store.js')
      const full=await api._request('GET','/design/feature-log/full')
      return {log:full.feature_log,geometry:store.getState().currentGeometry.map(n=>n.backbone_position).sort((a,b)=>a[0]-b[0]||a[1]-b[1]||a[2]-b[2])}
    })
    const original=await read()
    await page.evaluate(()=>document.getElementById('menu-file-sharing').click())
    await page.locator('#share-link-dialog [data-create]').click()
    await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({timeout:30000})
    const displayPassword=await page.locator('#share-link-dialog [data-display-password]').inputValue()
    const url=new URL(await page.locator('#share-link-dialog [data-link]').inputValue());url.searchParams.set('test','1')
    await page.locator('#share-link-dialog [data-close]').click()
    const guest=await context.newPage();guest.on('pageerror',e=>errors.push(e.message));await guest.goto(url.href)
    await guest.locator('[data-demo-display-setup]').click()
    await guest.locator('#demo-display-password').fill(displayPassword)
    await guest.locator('#guest-name').fill('Sweep display');await guest.locator('#join-submit').click()
    await expect.poll(()=>guest.evaluate(()=>!!window.__preparedViewer?.current)).toBe(true)
    await guest.evaluate(()=>{
      window.__sweepRevisions=[]
      let last=''
      window.__sweepMonitor=setInterval(()=>{const v=window.__preparedViewer.current;if(v&&v.data.sourceHash!==last){last=v.data.sourceHash;window.__sweepRevisions.push({hash:last,at:Date.now()})}},25)
    })
    const guestHash=()=>guest.evaluate(()=>window.__preparedViewer.current.data.sourceHash)
    const hostHash=()=>page.evaluate(async()=>{
      const {store}=await import('/src/state/store.js')
      const bytes=new TextEncoder().encode(JSON.stringify(store.getState().currentDesign))
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('')
    })
    await page.getByRole('button',{name:'Help',exact:true}).click()
    await page.click('#menu-help-view-vr')
    let status
    await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid)pid=status.pid;return status.running&&!!status.scrywrite_socket},{timeout:100000}).toBe(true)
    await page.evaluate(()=>document.querySelector('.presentation-perspective').dispatchEvent(new CustomEvent('click',{detail:{nativeVR:true}})))
    await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed','true')
    const previewSamples=[]
    page.on('response',response=>{if(response.url().endsWith('/preview')){const body=response.request().postData();previewSamples.push({at:Date.now(),status:response.status(),bytes:body?.length,body:body?JSON.parse(body):null})}})
    const cameraSamples=[]
    page.on('response',async response=>{if(response.url().includes('/broadcast/camera')){const value=await response.json().catch(()=>null);cameraSamples.push({at:Date.now(),status:response.status(),camera:value?.camera,revision:value?.revision,error:value?.error})}})
    const profiles=process.env.NADOC_VR_SWEEP_VALIDATE==='1'?['steady_fast','steady_deliberate','variable_fast','variable_deliberate']:[process.env.NADOC_VR_PROFILE||'steady_fast']
    for(const preset of profiles){
      await guest.setViewportSize(preset.startsWith('variable')?{width:390,height:844}:{width:1280,height:720})
      const before=await read(), output=info.outputPath(preset)
      const sampleStart=cameraSamples.length
      let finished=false, captured=false
      const probe=execute(path.join(root,'.venv/bin/python'),['-m','tools.vr_workflows.sweep_edit_probe',status.scrywrite_socket,output,preset],{cwd:root,timeout:150000,env:{...process.env,NADOC_SWEEP_PREVIEW_REVIEW:'1',NADOC_SWEEP_NODE_DRAG:'1'}}).finally(()=>{finished=true})
      const observe=(async()=>{
        const stages=new Set()
        while(!finished){
          for(const stage of ['opened','cancelled','editing','committed']){
            if(stages.has(stage) || !await fs.access(path.join(output,stage+'-ready')).then(()=>true,()=>false))continue
            const visible=stage==='opened'||stage==='editing'
            await expect.poll(()=>guest.evaluate(()=>!!window.__preparedViewer.runtime.scene.getObjectByName('vr-sweep-preview')?.visible),{timeout:10000}).toBe(visible)
            await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed','true')
            if(visible){
              expect(await guest.evaluate(()=>window.__preparedViewer.runtime.scene.getObjectByName('vr-sweep-preview').children[1].count)).toBe(4)
              await guest.locator('#canvas').screenshot({path:info.outputPath(preset+'-'+stage+'-preview.png')})
              // Hide only the actual preview, preserving the model, camera and menu graphics.
              await guest.evaluate(()=>window.__preparedViewer.runtime.scene.getObjectByName('vr-sweep-preview').children.forEach(o=>{o.visible=false}))
              try {await guest.locator('#canvas').screenshot({path:info.outputPath(preset+'-'+stage+'-no-preview.png')})}
              finally {await guest.evaluate(()=>window.__preparedViewer.runtime.scene.getObjectByName('vr-sweep-preview').children.forEach(o=>{o.visible=true}))}
              await execute(path.join(root,'.venv/bin/python'),['-c',`from PIL import Image, ImageChops
import sys
left=Image.open(sys.argv[1]).convert('RGB');right=Image.open(sys.argv[2]).convert('RGB')
changed=sum(max(p)>30 for p in ImageChops.difference(left,right).getdata())
assert changed>100, f'Sweep preview not visible: {changed} changed pixels'
print(changed)`,info.outputPath(preset+'-'+stage+'-preview.png'),info.outputPath(preset+'-'+stage+'-no-preview.png')],{cwd:root})
              captured=true
            }
            stages.add(stage);await fs.writeFile(path.join(output,stage+'-reviewed'),'reviewed')
          }
          await new Promise(resolve=>setTimeout(resolve,100))
        }
        expect([...stages]).toEqual(['opened','cancelled','editing','committed'])
      })()
      try { await Promise.all([probe,observe]) }
      finally { await fs.writeFile(info.outputPath(preset+'-camera-samples.json'),JSON.stringify(cameraSamples,null,2));await fs.writeFile(info.outputPath(preset+'-preview-samples.json'),JSON.stringify(previewSamples,null,2)) }
      expect(captured).toBe(true)
      await expect(page.locator('.presentation-perspective')).toHaveAttribute('aria-pressed','true')
      await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed','true')
      const result=JSON.parse(readFileSync(path.join(output,'result.json'),'utf8'))
      const samples=cameraSamples.slice(sampleStart)
      expect(samples.length).toBeGreaterThan(20)
      expect(samples.every(s=>s.status===200 && s.camera?.source==='headset')).toBe(true)
      const gaps=samples.slice(1).map((s,i)=>s.camera.expiresAt-samples[i].camera.expiresAt)
      expect(Math.max(...gaps)).toBeLessThan(1500)
      expect(Date.now()-samples.at(-1).at).toBeLessThan(1500)
      const checkFollow=async()=>{
        await expect.poll(async()=>{
          const expected=cameraSamples.at(-1)?.camera, actual=await guest.evaluate(()=>window.__preparedViewer.captureCamera())
          if(!expected)return false
          const direction=c=>{const d=c.target.map((v,i)=>v-c.position[i]),n=Math.hypot(...d);return d.map(v=>v/n)}
          const a=direction(actual),b=direction(expected)
          return Date.now()-cameraSamples.at(-1).at<1500 && Math.hypot(...actual.position.map((v,i)=>v-expected.position[i]))/expected.unitsPerMeter<.05 && a.reduce((sum,v,i)=>sum+v*b[i],0)>.995
        },{timeout:20000}).toBe(true)
      }
      await checkFollow()
      const edited=await read()
      expect(edited.log.map(e=>e.id)).toEqual(original.log.map(e=>e.id))
      expect(edited.log[0].params.points_nm).toEqual(result.after)
      expect(edited.geometry).not.toEqual(before.geometry)
      let expectedHash=await hostHash()
      try {
        await expect.poll(async()=>{expectedHash=await hostHash();return await guestHash()===expectedHash},{timeout:30000}).toBe(true)
      } catch(error) {
        await fs.writeFile(info.outputPath(`${preset}-sharing-failure.json`),JSON.stringify({expectedHash,currentHash:await hostHash(),guestHash:await guestHash(),
          guest:await guest.evaluate(()=>({revisions:window.__sweepRevisions,status:document.querySelector('[data-connection]')?.textContent})),
          hostStatus:await page.locator('body').innerText()},null,2))
        throw error
      }
      expect((await read()).log[0].params.points_nm).toEqual(result.after)
      const received=await guest.evaluate(hash=>window.__sweepRevisions.find(r=>r.hash===hash),expectedHash)
      await fs.writeFile(info.outputPath(`${preset}-delivery.json`),JSON.stringify({nativeCommitSeconds:result.commit_seconds,
        guestSecondsFromApplyReach:received?(received.at-result.started_ms)/1000:null,sourceHash:expectedHash},null,2))
      await guest.screenshot({path:info.outputPath(`${preset}-guest.png`)})
      await guest.locator('#canvas').screenshot({path:info.outputPath(preset+'-model.png')})
      await guest.evaluate(()=>{window.__preparedViewer.current.scene.visible=false})
      try {await guest.locator('#canvas').screenshot({path:info.outputPath(preset+'-no-model.png')})}
      finally {await guest.evaluate(()=>{window.__preparedViewer.current.scene.visible=true})}
      await execute(path.join(root,'.venv/bin/python'),['-c',`from PIL import Image, ImageChops
import sys
left=Image.open(sys.argv[1]).convert('RGB');right=Image.open(sys.argv[2]).convert('RGB')
changed=sum(max(p)>30 for p in ImageChops.difference(left,right).getdata())
assert changed>100, f'Molecular scene not visible: {changed} changed pixels'
print(changed)`,info.outputPath(preset+'-model.png'),info.outputPath(preset+'-no-model.png')],{cwd:root})
      await page.evaluate(async()=>{const api=await import('/src/api/client.js');await api.undo();await api.refreshNativeVRScene({expected_design_id:api.currentDesignId(),expected_revision:api.currentRevisionWatermark()})})
      await expect.poll(async()=>await guestHash()===await hostHash(),{timeout:30000}).toBe(true)
      await checkFollow()
      const undone=await read()
      expect(undone.geometry).toEqual(before.geometry)
      expect(undone.log[0].params.points_nm).toEqual(before.log[0].params.points_nm)
      await page.evaluate(async()=>{const api=await import('/src/api/client.js');await api.redo();await api.refreshNativeVRScene({expected_design_id:api.currentDesignId(),expected_revision:api.currentRevisionWatermark()})})
      expect((await read()).geometry).toEqual(edited.geometry)
      await expect.poll(async()=>await guestHash()===await hostHash(),{timeout:30000}).toBe(true)
      await checkFollow()
    }
    expect(errors).toEqual([])
  } finally {
    const status=await(await request.get(`${base}/api/vr/status`)).json()
    if(pid&&status.pid===pid)await request.post(`${base}/api/vr/stop`)
  }
})
