import { test, expect } from '@playwright/test'

async function boot(page, tag, ordinary = false) {
  const doc = `__e2e__g4-${tag}`
  const api = `${process.env.NADOC_E2E_API_BASE}/api`
  const headers = {'X-NADOC-Doc':doc}
  const r = await page.request.post(`${api}/design/import/aptamer`, {headers,data:{template_id:'148D'}})
  expect(r.ok(),await r.text()).toBeTruthy()
  const {design} = await r.json()
  if (ordinary) {
    design.helices.push({id:'ordinary',axis_start:{x:6,y:0,z:0},axis_end:{x:6,y:0,z:5},length_bp:15})
    design.strands.push({id:'staple',strand_type:'staple',sequence:'A'.repeat(15),color:'#3399ff',domains:[{helix_id:'ordinary',start_bp:0,end_bp:14,direction:'FORWARD'}]})
    const loaded = await page.request.post(`${api}/design/import`,{headers,data:{content:JSON.stringify(design)}})
    expect(loaded.ok(),await loaded.text()).toBeTruthy()
  }
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(()=>window.__nadocTest?.store)
  await page.evaluate(async()=> { const api = await import('/src/api/client.js'); await api.getDesign(); await api.getGeometry() })
  await page.waitForFunction(()=>window.__nadocTest.store.getState().currentGeometry?.length)
  await page.evaluate(()=>document.getElementById('welcome-screen')?.classList.add('hidden'))
  await page.evaluate(()=>window.__nadocTest.setRepresentation('full'))
  await page.locator('#canvas').click({position:{x:5,y:5}})
  await page.keyboard.press('f')
  return {doc,design,api,headers}
}

test('G4 and ordinary staple ends connect through the 3D force tool',async({page})=>{
  test.setTimeout(90_000)
  const {design} = await boot(page,'forced',true)
  const sid = design.strands[0].id
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.getEndBeadScreenPositions().length)).toBe(4)
  await page.evaluate(()=>document.querySelector('#view-tools [data-key="fxover"]').click())
  const ends = await page.evaluate(()=>window.__nadocTest.getEndBeadScreenPositions())
  const a = ends.find(e=>e.strand_id===sid && e.is_three_prime)
  const b = ends.find(e=>e.strand_id==='staple' && e.is_five_prime)
  await page.mouse.click(a.x,a.y)
  await expect(page.locator('#mode-indicator')).toContainText('another strand')
  const done = page.waitForResponse(r=>r.url().endsWith('/design/forced-ligation') && r.request().method()==='POST')
  await page.mouse.click(b.x,b.y)
  expect((await done).ok()).toBeTruthy()
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign.strands.length)).toBe(1)
  const merged = await page.evaluate(()=>window.__nadocTest.store.getState().currentDesign.strands[0])
  expect(merged.sequence).toBe('GGTTGGTGTGGTTGG'+'A'.repeat(15))
  expect(await page.evaluate(()=>window.__nadocTest.getRenderedCrossoverArcCount())).toBeGreaterThan(0)
  await page.keyboard.press('Escape')
  await page.evaluate(async()=> (await import('/src/api/client.js')).undo())
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign.strands.length)).toBe(2)
  await page.evaluate(async()=> (await import('/src/api/client.js')).redo())
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign.strands.length)).toBe(1)
})

test('cadnano draws the G4 icon and painting a partner creates a 3D duplex',async({page,context})=>{
  test.setTimeout(90_000)
  await context.addInitScript(()=>{
    const original = CanvasRenderingContext2D.prototype.fillText
    window.__g4Labels = []
    CanvasRenderingContext2D.prototype.fillText = function(text,...args) {
      if(String(text).startsWith('G4')) window.__g4Labels.push(text)
      return original.call(this,text,...args)
    }
  })
  await context.route('**/src/cadnano-editor/pathview.js', async route=>{
    const response = await route.fetch()
    const body = (await response.text()).replace('  // ── Public interface', `
      window.__g4Path = { point: (hid,bp,dir) => {
        const info = _rowMap.get(hid)
        return {x:_bpCenterX(bp)*_zoom+_panX,y:info[dir==='FORWARD'?'fwdY':'revY']*_zoom+_panY}
      }, design:()=>_design }
      // ── Public interface`)
    await route.fulfill({response,body})
  })
  const {doc,design} = await boot(page,'cadnano')
  const original = await page.evaluate(()=>window.__nadocTest.store.getState().currentGeometry.map(n=>n.backbone_position))
  const editor = await context.newPage()
  await editor.goto(`/cadnano-editor.html?doc=${doc}`)
  await editor.waitForFunction(()=>window.__g4Path?.design()?.strands.length)
  await expect.poll(()=>editor.evaluate(()=>window.__g4Labels.includes('G4'))).toBe(true)
  await editor.locator('#tool-pencil').click()
  const points = await editor.evaluate(hid=>[0,14].map(bp=>window.__g4Path.point(hid,bp,'REVERSE')),design.helices[0].id)
  const box = await editor.locator('#pathview-canvas').boundingBox()
  await editor.mouse.move(box.x+points[0].x,box.y+points[0].y)
  await editor.mouse.down()
  await editor.mouse.move(box.x+points[1].x,box.y+points[1].y,{steps:14})
  const done = editor.waitForResponse(r=>r.url().endsWith('/design/strands') && r.request().method()==='POST')
  await editor.mouse.up()
  expect((await done).ok()).toBeTruthy()
  await expect.poll(()=>editor.evaluate(()=>window.__g4Labels.includes('G4 · duplex'))).toBe(true)
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentGeometry.length)).toBe(30)
  const pair = await page.evaluate(()=>window.__nadocTest.store.getState().currentGeometry.filter(n=>n.bp_index===7).map(n=>n.backbone_position))
  expect(Math.hypot(...pair[0].map((v,i)=>v-pair[1][i]))).toBeGreaterThan(1)
  for (const repr of ['ballstick','cylinders','full']) await page.evaluate(r=>window.__nadocTest.setRepresentation(r),repr)
  await page.evaluate(async()=> (await import('/src/api/client.js')).undo())
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentGeometry.map(n=>n.backbone_position))).toEqual(original)
})

test('resized G4 tails can be paired in the Overhang Connections sidebar',async({page})=>{
  test.setTimeout(90_000)
  const {api,headers,design} = await boot(page,'sidebar',true)
  // Give the ordinary staple scaffold coverage, then resize both attachment ends.
  const scaffold = await page.request.post(`${api}/design/strands`,{headers,data:{strand_type:'scaffold',sequence:'T'.repeat(15),domains:[{helix_id:'ordinary',start_bp:14,end_bp:0,direction:'REVERSE'}]}})
  expect(scaffold.ok(),await scaffold.text()).toBeTruthy()
  const resized = await page.request.post(`${api}/design/strand-end-resize`,{headers,data:{entries:[
    {strand_id:design.strands[0].id,helix_id:design.helices[0].id,end:'5p',delta_bp:-4},
    {strand_id:'staple',helix_id:'ordinary',end:'3p',delta_bp:4},
  ]}})
  expect(resized.ok(),await resized.text()).toBeTruthy()
  const grown = (await resized.json()).design
  const a = grown.overhangs.find(o=>o.helix_id===design.helices[0].id)
  const b = grown.overhangs.find(o=>o.helix_id==='ordinary')
  expect(a).toBeTruthy(); expect(b).toBeTruthy()
  await page.reload()
  await page.waitForFunction(()=>window.__nadocTest?.store)
  await page.evaluate(async()=> { const api = await import('/src/api/client.js'); await api.getDesign(); await api.getGeometry() })
  await page.waitForFunction(()=>window.__nadocTest.store.getState().currentDesign?.overhangs.length===2)
  await page.evaluate(()=>{
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.querySelector('#right-tab-strip [data-tab="overhangs"]')?.click()
    document.getElementById('oconn-heading').click()
  })
  await page.locator('#oconn-select-a').selectOption(a.id,{force:true})
  await page.locator('#oconn-select-b').selectOption(b.id,{force:true})
  await page.evaluate(()=>{
    document.getElementById('oconn-button-box').click()
    document.querySelector('#oconn-popover [data-variant="root-to-root"]').click()
  })
  await expect(page.locator('#oconn-generate')).toBeEnabled()
  await page.evaluate(()=>document.getElementById('oconn-generate').click())
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign.duplexes.length)).toBe(1)
  const result = await page.evaluate(()=>window.__nadocTest.store.getState().currentDesign)
  expect(result.strands.find(s=>s.id===design.strands[0].id).sequence).toContain('GGTTGGTGTGGTTGG')
  await page.evaluate(async()=> (await import('/src/api/client.js')).undo())
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign.duplexes.length)).toBe(0)
  await page.evaluate(async()=> (await import('/src/api/client.js')).redo())
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign.duplexes.length)).toBe(1)
})
