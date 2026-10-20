import {test,expect} from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import {execFileSync} from 'node:child_process'
const base=process.env.NADOC_E2E_API_BASE
// Inventory: wrapper-owned Archive workspace (metadata, analysis caches, prefixed
// designs, project history), TMPDIR (VR snapshots/sockets), isolated Vite credential.
// Wrapper TemporaryDirectory + global teardown remove these on success/failure;
// afterEach stops only our viewer PID. Evidence is in Playwright output only.
let pid,log,ownedStatus,offset=0
const windows=[]
test.afterEach(async({request},info)=>{
 if(log&&fs.existsSync(log))fs.writeFileSync(info.outputPath('viewer.log'),fs.readFileSync(log).subarray(offset))
 fs.writeFileSync(info.outputPath('windows.json'),JSON.stringify(windows,null,2))
 if(pid){
  const s=await(await request.get(`${base}/api/vr/status`)).json()
  if(s.pid===pid){
   await request.post(`${base}/api/vr/stop`)
   await expect.poll(async()=>!!(await(await request.get(`${base}/api/vr/status`)).json()).running).toBe(false)
   const dirs=[ownedStatus?.pose_journal_directory&&path.dirname(ownedStatus.pose_journal_directory),ownedStatus?.scrywrite_socket&&path.dirname(ownedStatus.scrywrite_socket)].filter(Boolean)
   for(const dir of dirs){expect(path.basename(dir)).toMatch(/^(viewer-|v-)/);fs.rmSync(dir,{recursive:true,force:true})}
   fs.writeFileSync(info.outputPath('runtime-cleanup.json'),JSON.stringify({pid,removed:dirs.every(d=>!fs.existsSync(d)),directories:dirs}))
  }
 }
 pid=null
})
test('CPD default atomistic playback cadence and submitted stereo',async({page,request},info)=>{
 test.skip(!process.env.NADOC_CPD_BENCHMARK_JOB,'Use the isolated CPD benchmark launcher')
 const errors=[],frames=[],requests=[];let snapshot,seq=0
 page.on('pageerror',e=>errors.push(e.message))
 page.on('request',r=>{
  if(r.url().endsWith('/api/vr/simulations')){snapshot=r.postDataJSON();if(snapshot.trajectory?.phase==='ready')frames.push({at:Date.now(),...snapshot.trajectory})}
  if(/trajectory-bin|frames-atomistic|frames-solvent|view-tools/.test(r.url()))requests.push({at:Date.now(),url:r.url(),bytes:r.postDataBuffer()?.length||0})
 })
 if(process.env.NADOC_CPD_BASELINE)for(const file of ['scene/vr_simulation_trajectory.js','ui/oxdna_display.js'])await page.route(`**/src/${file}*`,r=>r.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(process.env.NADOC_CPD_BASELINE,path.basename(file)),'utf8')}))
 const fixture=process.env.NADOC_CPD_BENCHMARK_FIXTURE
 await page.route('**/api/library/files',async route=>{const r=await route.fetch();await route.fulfill({response:r,json:[...await r.json(),{path:fixture,name:fixture.slice(0,-6),type:'part',size_bytes:0,mtime_iso:new Date().toISOString()}]})})
 await page.route('**/api/vr/launch',route=>route.continue({postData:JSON.stringify({...route.request().postDataJSON(),scrywrite_place_scene_in_view:true})}))
 await page.addInitScript(()=>{
  performance.setResourceTimingBufferSize(10000)
  if(!window.__nadocVRPlaybackTrace){
   window.__nadocVRPlaybackEvents=[];window.__nadocVRPlaybackTraceDropped=0
   let source=null
   window.__nadocVRPlaybackTrace=e=>{if(e.stage==='companions_end')source=e.source;if(window.__nadocVRPlaybackEvents.length<20000)window.__nadocVRPlaybackEvents.push({source,...e});else window.__nadocVRPlaybackTraceDropped++}
   new PerformanceObserver(list=>{for(const e of list.getEntries())window.__nadocVRPlaybackTrace({stage:'longtask',epoch_ms:performance.timeOrigin+e.startTime,duration_ms:e.duration})}).observe({type:'longtask',buffered:true})
  }
 })
 // Match headset-only use through the existing desktop drawing preference.
 if(process.env.NADOC_CPD_DESKTOP_RENDERING !== 'on')await page.addInitScript(()=>localStorage.setItem('nadoc:vr-desktop-3d','off'))
 await page.goto('/?doc=__e2e__cpd-playback&scrywrite=transactions')
 await page.waitForFunction(()=>!!window.__nadocTest)
 await page.locator(`[data-library-path="${fixture}"]`).click()
 await expect(page.locator('#welcome-screen')).not.toBeVisible()
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 await page.locator('.engine-selector-btn[data-engine="namd"]').click()
 await expect(page.locator('#simulate-jobs-list [data-job-id]').first()).toBeVisible()
 await page.evaluate(()=>document.getElementById('menu-help-view-vr').click())
 let status
 await expect.poll(async()=>{status=await(await request.get(`${base}/api/vr/status`)).json();if(status.pid&&!pid){pid=status.pid;ownedStatus=status;log=status.log_path;offset=fs.existsSync(log)?fs.statSync(log).size:0}return status.running&&!!status.scrywrite_socket},{timeout:90000}).toBe(true)
 await expect.poll(()=>snapshot?.jobs.length,{timeout:30000}).toBeGreaterThan(0)
 async function action(id,extra={}){
  const sequence=++seq
  await page.evaluate(event=>window.__nadocTest.scrywrite.dispatch(event),{type:'simulation',id,version:snapshot.version,sequence,...extra})
  await expect.poll(()=>snapshot.acknowledged,{timeout:15000}).toBe(sequence)
  // Request observation precedes the publisher's response/identity commit.
  await page.waitForTimeout(100)
 }
 await expect.poll(async()=>{
  if(!snapshot.selected){
   const job=snapshot.jobs.find(j=>!j.id.endsWith(':tree'))
   if(job)await action(job.id)
  }
  return snapshot.selected
 },{timeout:30000,intervals:[500]}).toBe(process.env.NADOC_CPD_BENCHMARK_JOB)
 // The application safely rejects stale control versions while metadata changes.
 // Confirm the read-only selection, and retry only when no trajectory was selected.
 await expect.poll(async()=>{
  if(!snapshot.trajectory){
   const mode=snapshot.controls.find(c=>c.kind==='mode'&&/traj/i.test(c.group)&&c.enabled)
   if(mode)await action(mode.id)
  }
  return snapshot.trajectory?.available || 0
 },{timeout:60000,intervals:[500]}).toBeGreaterThan(0)
 // Use the established simulation tour handoff: load the default trajectory
 // first, then switch styles on that displayed trajectory. This avoids racing
 // the live-result teardown with a design-only atom rebuild.
 await action('t:load')
 await expect.poll(()=>snapshot.trajectory?.phase,{timeout:240000,intervals:[500]}).toBe('ready')
 for(const representation of (process.env.NADOC_CPD_STYLES||'ballstick,stick,vdw').split(',')){
  await page.evaluate(r=>document.getElementById('menu-view-atomistic-'+r).click(),representation)
  await expect(page.locator('#menu-view-atomistic-'+representation)).toHaveClass(/is-checked/, {timeout:120000})
  await page.waitForTimeout(2000)
  const loadStart=Date.now();await action('t:load')
  await expect.poll(()=>snapshot.trajectory?.phase,{timeout:240000,intervals:[500]}).toBe('ready')
  windows.push({name:'load',representation,start:loadStart,end:Date.now(),count:snapshot.trajectory.count,message:snapshot.trajectory.message})
  await page.waitForTimeout(2000)
  for(const smooth of (process.env.NADOC_CPD_SAVED_ONLY ? [false] : [false,true])){
   if(snapshot.trajectory.smooth!==smooth)await action('t:smooth')
   await action('t:seek',{value:0});await expect.poll(()=>snapshot.trajectory.phase,{timeout:60000}).toBe('ready')
   const cdp=process.env.NADOC_CPD_PROFILE ? await page.context().newCDPSession(page) : null
   if(cdp){await cdp.send('Profiler.enable');await cdp.send('Profiler.start')}
   await page.evaluate(()=>{window.__nadocVRPlaybackEvents=[];window.__nadocVRPlaybackTraceDropped=0})
   const desktopBefore=await page.evaluate(()=>window.__nadocTest.viewerFrameState())
   await action('t:play');const start=Date.now();await page.waitForTimeout(12000)
   if(snapshot.trajectory.playing)await action('t:play')
   const end=Date.now()
   const desktopAfter=await page.evaluate(()=>window.__nadocTest.viewerFrameState())
   const pipeline=await page.evaluate(()=>({events:window.__nadocVRPlaybackEvents,dropped:window.__nadocVRPlaybackTraceDropped}))
   fs.writeFileSync(info.outputPath(`${representation}-${smooth}-pipeline.json`),JSON.stringify(pipeline))
   expect(pipeline.dropped).toBe(0)
   const transport=await page.evaluate(({start,end})=>performance.getEntriesByType('resource').filter(r=>r.name.endsWith('/api/vr/view-tools')&&performance.timeOrigin+r.startTime>=start&&performance.timeOrigin+r.startTime<=end).map(r=>({start:performance.timeOrigin+r.startTime,duration:r.duration,response:r.responseStart-r.requestStart})),{start,end})
   fs.writeFileSync(info.outputPath(`${representation}-${smooth}-transport.json`),JSON.stringify(transport))
   if(cdp){const {profile}=await cdp.send('Profiler.stop');fs.writeFileSync(info.outputPath(`${representation}-${smooth}.cpuprofile`),JSON.stringify(profile));await cdp.detach()}
   const selected=frames.filter(f=>f.at>=start&&f.at<=end)
   const unique=selected.filter((f,i)=>i===0||f.index!==selected[i-1].index)
   const gaps=unique.slice(1).map((f,i)=>f.at-unique[i].at).sort((a,b)=>a-b)
   const io=requests.filter(r=>r.at>=start&&r.at<=end&&!r.url.endsWith('view-tools'))
   windows.push({name:'play',representation,smooth,start,end,desktopBefore,desktopAfter,frames:unique.length,gap_p50:gaps[Math.floor(gaps.length*.5)],gap_p95:gaps[Math.floor(gaps.length*.95)],gap_max:gaps.at(-1),coordinateRequests:io.length,viewUploads:requests.filter(r=>r.at>=start&&r.at<=end&&r.url.endsWith('view-tools')).length})
   fs.writeFileSync(info.outputPath('windows.json'),JSON.stringify(windows,null,2))
   if(!process.env.NADOC_CPD_BASELINE){expect(io).toHaveLength(0);expect.soft(unique.length).toBeGreaterThan(80)}
  }
  // Capture only after timing. Real submitted eyes and identifiable model pixels.
  const capture=info.outputPath('stereo-'+representation)
  execFileSync('../.venv/bin/python',['-c',`from frontend.scrywrite.mcp_bridge import Bridge\nfrom tools.vr_motion.session import LiveSession\nimport sys,numpy as np\nfrom pathlib import Path\nl=LiveSession(Bridge(sys.argv[1]),physical=True,allow_transactions=True)\ne,_=l.capture_to(Path(sys.argv[2]),files=['evidence.json','left.png','right.png','left.classes.u8','right.classes.u8'],discard_source=True)\nassert e['state']['representation']==sys.argv[3], e['state']['representation']\nassert all(np.count_nonzero(np.fromfile(Path(sys.argv[2])/(eye['eye']+'.classes.u8'),dtype=np.uint8)==1)>100 for eye in e['eyes'])`,status.scrywrite_socket,capture,representation],{cwd:process.cwd(),env:{...process.env,PYTHONPATH:path.resolve('..')},timeout:30000})
 }
 fs.writeFileSync(info.outputPath('requests.json'),JSON.stringify(requests))
 expect(errors).toEqual([])
})
