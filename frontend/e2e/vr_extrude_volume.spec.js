import {test, expect} from '@playwright/test'
import {execFileSync} from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'

// No fixture import: the only topology creation is trigger painting + Confirm.
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'explicit physical runtime opt-in')
const doc='__e2e__extrude-volume-tour'
const base=process.env.NADOC_E2E_API_BASE
const square=process.env.NADOC_VR_LATTICE==='SQUARE'
const length=square?48:42
let pid

test.afterEach(async ({request}) => {
  const status=await (await request.get(`${base}/api/vr/status`)).json()
  if(pid && status.pid===pid) {
    await request.post(`${base}/api/vr/stop`)
    await expect.poll(async()=>(await (await request.get(`${base}/api/vr/status`)).json()).running,{timeout:20000}).toBe(false)
  }
})

test(`new part → right Tools Extrude → ${square?'square 2×3':'canonical 6HB'} → subsection volume`, async ({page,request},info) => {
  test.setTimeout(340000)
  await page.goto(`/?doc=${doc}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name',square?'__e2e__Fresh VR Square':'__e2e__Fresh VR 6HB')
  if(square)await page.locator('input[name="new-lattice-type"][value="SQUARE"]').check()
  await page.getByRole('button',{name:'Create',exact:true}).click()
  const read=()=>page.evaluate(async ()=>(await import('/src/state/store.js')).store.getState().currentDesign)
  expect((await read()).helices).toHaveLength(0)
  await page.locator('.menu-item').filter({hasText:'Help'}).first().hover()
  await page.click('#menu-help-view-vr')
  let status
  await expect.poll(async()=>{
    status=await (await request.get(`${base}/api/vr/status`)).json()
    if(status.pid)pid=status.pid
    return status.running && !!status.scrywrite_socket
  },{timeout:30000}).toBe(true)
  const probe=(script,name,...args)=>execFileSync('uv',['run','python','-m',`tools.vr_workflows.${script}`,
    status.scrywrite_socket,info.outputPath(name),...args],{
    cwd:path.resolve(process.cwd(),'..'),encoding:'utf8',timeout:240000,env:process.env,stdio:['ignore','inherit','inherit']})
  probe('native_confirm_probe','extrude')
  const design=await read()
  expect(design.helices).toHaveLength(6)
  expect(design.lattice_type).toBe(square?'SQUARE':'HONEYCOMB')
  expect(design.helices.map(h=>h.grid_pos).sort()).toEqual(square?
    [[0,0],[0,1],[0,2],[1,0],[1,1],[1,2]]:[[0,1],[0,2],[0,3],[1,1],[1,2],[1,3]])
  expect(design.helices.every(h=>h.length_bp===length)).toBe(true)
  expect(design.lattice_frames).toHaveLength(1)
  if(square) {
    // Independent square-grid oracle: equal 2.25 nm perpendicular pitches.
    for(const h of design.helices) {
      const [row,col]=h.grid_pos
      expect(h.axis_start.x).toBeCloseTo(col*2.25,5)
      expect(h.axis_start.y).toBeCloseTo(row*2.25,5)
      expect(h.axis_start.z).toBeCloseTo(0,5)
    }
  } else {
  // Independent geometry oracle: a regular six-sided ring, not a six-cell rectangle.
  const points=design.helices.map(h=>[h.axis_start.x,h.axis_start.y])
  const center=[0,1].map(a=>points.reduce((sum,p)=>sum+p[a],0)/6)
  const radii=points.map(p=>Math.hypot(p[0]-center[0],p[1]-center[1]))
  expect(Math.min(...radii)).toBeGreaterThan(1)
  expect(Math.max(...radii)-Math.min(...radii)).toBeLessThan(1e-5)
  const angles=points.map(p=>Math.atan2(p[1]-center[1],p[0]-center[0])).sort((a,b)=>a-b)
  for(let i=0;i<6;i++)expect((angles[(i+1)%6]-angles[i]+Math.PI*2)%(Math.PI*2)).toBeCloseTo(Math.PI/3,5)
  }
  await page.locator('#canvas').click({position:{x:30,y:30}})
  await page.keyboard.press('f')
  await page.screenshot({path:info.outputPath('desktop-6hb.png')})
  probe('extrude_volume_probe','volume-create','create')
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  // Desktop style edit must reach the same native volume. Geometry comes from native controls.
  await page.locator('.view-volume-representation').selectOption('beads')
  await expect.poll(()=>page.evaluate(()=>window.__NADOC_VIEW_VOLUMES__.volumes()[0].representation)).toBe('beads')
  probe('extrude_volume_probe','volume-compare','compare')
  const layers=await page.evaluate(()=>window.__NADOC_VIEW_VOLUMES__.layers().map(l=>({id:l.volume.id,count:l.keys.size})))
  expect(layers).toHaveLength(1)
  expect(layers[0].count).toBeGreaterThan(0)
  expect(layers[0].count).toBeLessThan(6*length*2)
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
  expect(onDisk.view_volumes).toEqual(saved.view_volumes)
  fs.copyFileSync(file,info.outputPath(square?'fresh-square.nadoc':'fresh-6hb.nadoc'))
  await request.post(`${base}/api/vr/stop`)
  await expect.poll(async()=>(await (await request.get(`${base}/api/vr/status`)).json()).running,{timeout:20000}).toBe(false)
  const reloaded=await page.context().newPage()
  await reloaded.goto('/?doc=__e2e__extrude-volume-reloaded')
  await reloaded.evaluate(async file=>(await import('/src/api/client.js')).loadDesign(file),file)
  const restored=await reloaded.evaluate(async ()=>(await import('/src/state/store.js')).store.getState().currentDesign)
  expect(restored.lattice_type).toBe(design.lattice_type)
  expect(restored.helices).toEqual(saved.helices)
  expect(restored.view_volumes).toEqual(saved.view_volumes)
  await reloaded.close()
})
