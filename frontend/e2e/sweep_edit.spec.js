import { test, expect } from '@playwright/test'
import { writeFile } from 'node:fs/promises'
import { checkLiveSweep } from './sweep_live_check.js'

// Persistent inventory: a __e2e__SweepEdit part and hidden project revisions,
// cleaned by global-teardown even on failure, inside the disposable workspace.
// Session caching is disabled. Screenshots and exported .nadoc stay inside Playwright outputDir.
test('edit a routed sweep after resizing and extrusion, preview, cancel, apply and reload', async ({ page }, info) => {
  test.setTimeout(120_000)
  await page.setViewportSize({width:1600,height:1000})
  const errors=[]
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', r => { if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`) })
  await page.goto('/?test=1&doc=__e2e__sweep-edit')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name','__e2e__SweepEdit')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async () => {
    const api=await import('/src/api/client.js')
    const {store}=await import('/src/state/store.js')
    if (!await api.createSweep({cells:[[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]],points_nm:[[0,0,0],[3,0,10],[10,0,17]],ligate_adjacent:false})) throw Error('sweep')
    let d=store.getState().currentDesign
    const s=d.strands.find(s=>s.strand_type==='staple')
    const dm=s.domains[0]
    const post=async (path,body)=>{
      const result=await api._request('POST', `/design/${path}`, body)
      if(!result) throw Error(store.getState().lastError?.message || path)
      return result
    }
    await post('strand-end-resize',{entries:[{strand_id:s.id,helix_id:dm.helix_id,end:dm.direction==='FORWARD'?'3p':'5p',delta_bp:10}]})
    await post('nick',{helix_id:d.helices[1].id,bp_index:12,direction:'FORWARD'})
    const source=d.helices[1], bp=source.bp_start+source.length_bp-1
    const frame=await api.getDeformedFrame(bp,source.id)
    if(!await api.addBundleDeformedContinuation({cells:d.helices.map(h=>h.grid_pos),lengthBp:15,frame,refHelixId:source.id,sourceBp:bp})) throw Error('attached extrusion')
    // A downstream snapshot must no longer disable the sweep edit button.
    await post('bundle-segment',{cells:[[4,0]],length_bp:20,ligate_adjacent:false})
    await api.getDesign()
    await api.getGeometry()
    // Load the complete native document so the baseline includes every downstream feature.
    if (!await api.importDesign(JSON.stringify(await api._request('GET','/design/export')))) throw Error('fixture reload failed')
    window.__sweepBefore=JSON.stringify(store.getState().currentDesign)
    window.__independentHelix=store.getState().currentDesign.helices.at(-1).id
    window.__independentRender=()=>{
      const renderer=window.__nadocTest.getDesignRenderer()
      return renderer.getBackboneEntries().filter(e=>e.nuc.helix_id===window.__independentHelix).map(e=>({
        matrix:Array.from(e.instMesh.instanceMatrix.array.slice(e.id*16,e.id*16+16)),
        color:Array.from(e.instMesh.instanceColor.array.slice(e.id*3,e.id*3+3)),
        visible:e.instMesh.visible && renderer.getHelixCtrl().root.visible,
      }))
    }
    window.__independentBefore=window.__independentRender()
  })
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({position:[35,25,70],target:[5,0,16]}))
  const beforeFrame=await page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)).toBeGreaterThan(beforeFrame+1)
  await page.screenshot({path:info.outputPath('sweep-before-edit.png')})
  const edit=page.locator('#feature-log-panel-body [data-fl-row="1"]').getByRole('button',{name:'✎'})
  await expect(edit).toBeEnabled()
  await edit.click()
  await expect(page.locator('#sweep-panel')).toBeVisible()
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.getByRole('option',{name:/Point 2/}).click()
  await checkLiveSweep(page,info)
  const response=page.waitForResponse(r=>r.url().includes('/sweep/preview') && r.request().postData()?.includes('32'))
  await page.getByRole('spinbutton',{name:'Point Z (nm)'}).fill('32')
  const preview=await (await response).json()
  expect(preview.edit_backbones_nm.length).toBeGreaterThan(12)
  expect(await page.evaluate(ids=>ids.includes(window.__independentHelix),preview.edit_helix_ids)).toBe(false)
  expect(await page.evaluate(()=>({count:window.__independentBefore.length,
    unchanged:JSON.stringify(window.__independentRender())===JSON.stringify(window.__independentBefore),
    sections:window.__nadocTest.scene.getObjectByName('sweep-cross-sections').children.map(s=>({color:s.material.color.toArray(),opacity:s.material.opacity})),
  }))).toEqual({count:40,unchanged:true,sections:[
    {color:[.25,.7,.78],opacity:1},{color:[.25,.7,.78],opacity:1},{color:[1,.87,.5],opacity:1},
  ]})
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  const previewFrame=await page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)
  await expect.poll(()=>page.evaluate(()=>window.__nadocTest.viewerFrameState().rendered)).toBeGreaterThan(previewFrame+1)
  const arcs=await page.evaluate(()=>{
    const lines=window.__nadocTest.scene.getObjectByName('xoverArcLines').children
    return {count:lines.reduce((n,l)=>n+l.geometry.index.count/2,0),collapsed:lines.every(l=>{
      const idx=l.geometry.index.array,p=l.geometry.attributes.position.array
      for(let i=0;i<idx.length;i+=2) for(let k=0;k<3;k++) if(p[idx[i]*3+k]!==p[idx[i+1]*3+k])return false
      return true
    })}
  })
  expect(arcs.count).toBeGreaterThan(0)
  expect(arcs.collapsed).toBe(true)
  await page.screenshot({path:info.outputPath('sweep-edit-preview.png')})
  await page.locator('#canvas').focus(); await page.keyboard.press('Escape')
  await expect(page.locator('#sweep-panel')).not.toBeVisible()
  expect(await page.evaluate(async()=>{
    const before=JSON.parse(window.__sweepBefore), after=(await import('/src/state/store.js')).store.getState().currentDesign
    // Autosave updates camera/loadout metadata independently of the edit.
    return Object.keys(before).filter(k=>!['metadata','loadouts','active_loadout_id'].includes(k) && JSON.stringify(before[k])!==JSON.stringify(after[k]))
  })).toEqual([])
  await edit.click()
  await page.getByRole('option',{name:/Point 2/}).click()
  await page.getByRole('spinbutton',{name:'Point Z (nm)'}).fill('32')
  await expect(page.locator('#sweep-status')).toContainText('bp per helix')
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.click('#sweep-apply')
  await expect(page.locator('#sweep-panel')).not.toBeVisible()
  const result=await page.evaluate(async()=>{
    const {store}=await import('/src/state/store.js')
    const api=await import('/src/api/client.js')
    let d=store.getState().currentDesign
    const tip=d.deformations.find(o=>o.type==='sweep').params.points_nm.at(-1)
    const overhang=d.strands.flatMap(s=>s.domains).find(d=>d.overhang_id)
    const exported=await api._request('GET','/design/export')
    if(!await api.importDesign(JSON.stringify(exported))) throw Error('reload failed')
    return {tip,overhang:Math.abs(overhang.end_bp-overhang.start_bp)+1,exported}
  })
  expect({tip:result.tip,overhang:result.overhang}).toEqual({tip:[10,0,32],overhang:10})
  await writeFile(info.outputPath('sweep-edited.nadoc'), JSON.stringify(result.exported))
  await page.locator('#canvas').focus(); await page.keyboard.press('f')
  await page.screenshot({path:info.outputPath('sweep-edit-reloaded.png')})
  expect(errors).toEqual([])
})
