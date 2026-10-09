import {installAuditBrowserTrace, saveAuditBrowserTrace, importAuditDesign} from './helpers/vr_audit_design.js'
import {test, expect} from '@playwright/test'
import {execFileSync} from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'

// Audit mode imports the complete source before adding a part through painting.
// The default small fixture starts empty and creates topology only through VR.
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'explicit physical runtime opt-in')
const doc='__e2e__extrude-volume-tour'
const base=process.env.NADOC_E2E_API_BASE
const square=process.env.NADOC_VR_LATTICE==='SQUARE'
const legacy=process.env.NADOC_VR_LEGACY_SOURCE==='1'
const sliceReference=process.env.NADOC_VR_SLICE_REFERENCE==='1'
const length=square?48:42
let pid, liveSocket

test.afterEach(async ({request}) => {
  const status=await (await request.get(`${base}/api/vr/status`)).json()
  if(pid && status.pid===pid) {
    await request.post(`${base}/api/vr/stop`)
    await expect.poll(async()=>(await (await request.get(`${base}/api/vr/status`)).json()).running,{timeout:20000}).toBe(false)
  }
  if(liveSocket && !status.running) {
    const directory=path.dirname(liveSocket)
    if(path.basename(directory).startsWith('nadoc-scry-')) fs.rmSync(directory,{recursive:true,force:true})
  } else if(liveSocket && status.pid===pid) {
    const directory=path.dirname(liveSocket)
    if(path.basename(directory).startsWith('nadoc-scry-')) fs.rmSync(directory,{recursive:true,force:true})
  }
})

test(`${process.env.NADOC_VR_AUDIT_DESIGN ? path.basename(process.env.NADOC_VR_AUDIT_DESIGN,'.nadoc')+' + new part' : 'new part'} → right Tools Extrude → ${square?'square 2×3':'canonical 6HB'} → subsection volume`, async ({page,request},info) => {
  test.setTimeout(340000)
  if (process.env.NADOC_VR_FRAME_AUDIT === '1') { const cdp = await page.context().newCDPSession(page); await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: false }) }
  await page.goto(`/?doc=${doc}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name',square?'__e2e__Fresh VR Square':'__e2e__Fresh VR 6HB')
  if(square)await page.locator('input[name="new-lattice-type"][value="SQUARE"]').check()
  await page.getByRole('button',{name:'Create',exact:true}).click()
  const read=()=>page.evaluate(async ()=>({...(await import('/src/state/store.js')).store.getState().currentDesign,feature_log:(await (await import('/src/api/client.js'))._request('GET','/design/feature-log/full')).feature_log}))
  if (legacy || sliceReference) await page.evaluate(async ({square,sliceReference}) => {
    await (await import('/src/api/client.js')).addBundleSegment({
      cells:sliceReference?Array.from({length:8},(_,column)=>[0,column]):[[4,4],[4,5]],
      lengthBp:sliceReference?48:square?24:21})
  },{square,sliceReference})
  const imported=await importAuditDesign(page,info)
  const before=await read()
  if(!imported)expect(before.helices).toHaveLength(sliceReference?8:legacy?2:0)
  await page.locator('.menu-item').filter({hasText:'Help'}).first().hover()
  await page.click('#menu-help-view-vr')
  let status
  await expect.poll(async()=>{
    status=await (await request.get(`${base}/api/vr/status`)).json()
    if(status.pid)pid=status.pid
    if(status.scrywrite_socket)liveSocket=status.scrywrite_socket
    return status.running && !!status.scrywrite_socket
  },{timeout:30000}).toBe(true)
  const probe=(script,name,...args)=>execFileSync('uv',['run','python','-m',`tools.vr_workflows.${script}`,
    status.scrywrite_socket,info.outputPath(name),...args],{
    cwd:path.resolve(process.cwd(),'..'),encoding:'utf8',timeout:240000,env:process.env,stdio:['ignore','inherit','inherit']})
  probe('native_confirm_probe','extrude')
  const confirmed=JSON.parse(fs.readFileSync(info.outputPath('extrude/confirmed-closed-state.json'),'utf8'))
  expect(confirmed.extrude).toMatchObject({open:false,editor_active:false,configuration_active:false,
    confirm_pending:false,undo_available:true,cells:[],model_preview:[]})
  expect(confirmed.sidebars[1].open).toBe(false)
  expect(confirmed.status).toBe('COMMITTED')
  expect(confirmed.committed_feature_id).toBeTruthy()
  const design=await read()
  expect(design.feature_log).toHaveLength(before.feature_log.length+1)
  expect(design.feature_log.slice(0,-1)).toEqual(before.feature_log)
  const entry=design.feature_log.at(-1)
  expect(entry).toMatchObject({feature_type:'snapshot',op_kind:'extrude-frame',
    label:`Extrude frame: 6 cells × ${length} bp`,params:{length_bp:length,plane:'XY'}})
  expect(entry.design_snapshot_gz_b64).toBeTruthy();expect(entry.post_state_gz_b64).toBeTruthy()
  const featureRow=page.locator(`#feature-log-panel [data-fl-row="${design.feature_log.length}"]`)
  // Sidebar rail clicks add columns. Reuse the existing log so the later
  // Visualization column still fits alongside the workspace.
  if(!await featureRow.isVisible())await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  await expect(featureRow).toBeVisible()
  await expect(featureRow).toContainText(entry.label)
  await page.screenshot({path:info.outputPath('desktop-feature-log.png')})
  const priorIds=new Set(before.helices.map(h=>h.id))
  expect(design.helices.filter(h=>priorIds.has(h.id))).toEqual(before.helices)
  const created=design.helices.filter(h=>!priorIds.has(h.id))
  expect(created).toHaveLength(6)
  const oldClusterIds=new Set(before.cluster_transforms.map(c=>c.id))
  const newClusters=design.cluster_transforms.filter(c=>!oldClusterIds.has(c.id))
  expect(newClusters).toHaveLength(1)
  expect([...newClusters[0].helix_ids].sort()).toEqual(created.map(h=>h.id).sort())
  expect(design.cluster_transforms.filter(c=>oldClusterIds.has(c.id))).toEqual(before.cluster_transforms)
  expect(design.lattice_type).toBe(square?'SQUARE':'HONEYCOMB')
  expect(created.map(h=>h.grid_pos).sort()).toEqual(sliceReference?
    [[1,0],[1,1],[1,2],[2,0],[2,1],[2,2]]:square?
    [[0,0],[0,1],[0,2],[1,0],[1,1],[1,2]]:[[0,1],[0,2],[0,3],[1,1],[1,2],[1,3]])
  expect(created.every(h=>h.length_bp===length)).toBe(true)
  expect(design.lattice_frames).toHaveLength(before.lattice_frames.length+(legacy || sliceReference?0:1))
  if(square) {
    // Independent square-grid oracle: equal 2.25 nm perpendicular pitches.
    for(const h of created) {
      const [row,col]=h.grid_pos
      expect(h.axis_start.x).toBeCloseTo(col*2.25,5)
      expect(h.axis_start.y).toBeCloseTo(row*2.25,5)
      expect(h.axis_start.z).toBeCloseTo(0,5)
    }
    if(sliceReference) {
      // Independent source-relative oracle: the new rows remain exactly one
      // and two square pitches from the original 1x8 platform after commit.
      for(const h of created) {
        const source=before.helices.find(old=>old.grid_pos[1]===h.grid_pos[1])
        expect(h.axis_start.x-source.axis_start.x).toBeCloseTo(0,5)
        expect(h.axis_start.y-source.axis_start.y).toBeCloseTo(h.grid_pos[0]*2.25,5)
        expect(h.axis_start.z-source.axis_start.z).toBeCloseTo(0,5)
      }
    }
  } else {
  // Independent geometry oracle: a regular six-sided ring, not a six-cell rectangle.
  const points=created.map(h=>[h.axis_start.x,h.axis_start.y])
  const center=[0,1].map(a=>points.reduce((sum,p)=>sum+p[a],0)/6)
  const radii=points.map(p=>Math.hypot(p[0]-center[0],p[1]-center[1]))
  expect(Math.min(...radii)).toBeGreaterThan(1)
  expect(Math.max(...radii)-Math.min(...radii)).toBeLessThan(1e-5)
  const angles=points.map(p=>Math.atan2(p[1]-center[1],p[0]-center[0])).sort((a,b)=>a-b)
  for(let i=0;i<6;i++)expect((angles[(i+1)%6]-angles[i]+Math.PI*2)%(Math.PI*2)).toBeCloseTo(Math.PI/3,5)
  }
  if (process.env.NADOC_VR_CONFIRM_ONLY === '1') return
  await page.locator('#canvas').click({position:{x:30,y:30}})
  await page.keyboard.press('f')
  await page.screenshot({path:info.outputPath('desktop-6hb.png')})
  probe('extrude_volume_probe','volume-create','create')
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  // Desktop style edit must reach the same native volume. Geometry comes from native controls.
  await expect(page.locator('.view-volume-representation')).toBeVisible()
  await page.locator('.view-volume-representation').selectOption('beads')
  await expect.poll(()=>page.evaluate(()=>window.__NADOC_VIEW_VOLUMES__.volumes()[0].representation)).toBe('beads')
  probe('extrude_volume_probe','volume-compare','compare')
  const layers=await page.evaluate(()=>window.__NADOC_VIEW_VOLUMES__.layers().map(l=>({id:l.volume.id,count:l.keys.size})))
  expect(layers).toHaveLength(1)
  expect(layers[0].count).toBeGreaterThan(0)
  const totalNucleotides=await page.evaluate(async()=>(await (await import('/src/api/client.js'))._request('GET','/design/geometry')).nucleotides.length)
  // The volume must cover a strict subset of the complete loaded design.
  expect(layers[0].count).toBeLessThan(totalNucleotides)
  await page.screenshot({path:info.outputPath('desktop-subsection.png')})
  await expect.poll(async()=> (await read()).view_volumes[0]?.enabled).toBe(true)
  const saved=await read()
  expect(saved.helices).toEqual(design.helices)
  // Save the newly created part in place. Save As deliberately creates a new
  // project UUID, which would invalidate the still-bound VR editing session.
  const filename=saved.metadata.identity_last_known_path
  expect(filename).toMatch(/^__e2e__/)
  const result=await page.evaluate(async filename=>(await import('/src/api/client.js')).saveDesignToWorkspace(filename),filename)
  fs.writeFileSync(info.outputPath('saved-result.json'),JSON.stringify(result))
  const file=path.join(process.env.NADOC_WORKSPACE,filename)
  const onDisk=JSON.parse(fs.readFileSync(file,'utf8'))
  expect(onDisk.feature_log).toEqual(saved.feature_log)
  expect(onDisk.view_volumes).toEqual(saved.view_volumes)
  fs.copyFileSync(file,info.outputPath(square?'fresh-square.nadoc':'fresh-6hb.nadoc'))
  await request.post(`${base}/api/vr/stop`)
  await expect.poll(async()=>(await (await request.get(`${base}/api/vr/status`)).json()).running,{timeout:20000}).toBe(false)
  const reloaded=await page.context().newPage()
  await reloaded.goto('/?doc=__e2e__extrude-volume-reloaded')
  await reloaded.evaluate(async file=>(await import('/src/api/client.js')).loadDesign(file),file)
  const restored=await reloaded.evaluate(async ()=>({...(await import('/src/state/store.js')).store.getState().currentDesign,feature_log:(await (await import('/src/api/client.js'))._request('GET','/design/feature-log/full')).feature_log}))
  expect(restored.lattice_type).toBe(design.lattice_type)
  expect(restored.helices).toEqual(saved.helices)
  expect(restored.view_volumes).toEqual(saved.view_volumes)
  expect(restored.feature_log).toEqual(saved.feature_log)
  await reloaded.close()
})

// Optional read-only resource-condition evidence for full-size VR audits.
test.beforeEach(async ({page}) => { await installAuditBrowserTrace(page) })
test.afterEach(async ({page}, info) => { await saveAuditBrowserTrace(page, info) })
