// Read-only Plasmonic source, ephemeral __e2e__ document host and mocked simulation
// transport. Real EM API results are deleted in finally; no native simulation job,
// molecular edit or capture outside Playwright's cleaned output dirs. PNG downloads
// remain in Playwright's disposable browser context; no download.saveAs is used.
import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'

let pendingBatch = null
test.afterEach(async () => {
  if (!pendingBatch) return
  // A timed-out test closes its request fixture before finally runs. Use an
  // independent transport in teardown so the native worker/cache still stops.
  const response = await fetch(`${process.env.NADOC_E2E_API_BASE}/api/em-analysis/trajectories/${pendingBatch}`, {
    method:'DELETE', signal:AbortSignal.timeout(10000),
  })
  expect([200,404]).toContain(response.status)
  pendingBatch = null
})

test('loaded oxDNA trajectory confirms all frames and follows saved-frame EM maps', async ({page}) => {
  test.setTimeout(180000)
  const source = '../workspace/Plasmonic_test.nadoc', raw = await readFile(source)
  const hash = bytes=>createHash('sha256').update(bytes).digest('hex')
  const design = JSON.parse(raw), job = {job_id:'__e2e__em-trajectory',parent_job_id:'__e2e__em-relax',
    design_source_path:'Plasmonic_test.nadoc',design_name:'Plasmonic_test',status:'completed',backend:'CPU',created_at:1,
    current_stage_idx:1,run_config:{kind:'run'},stages:[{name:'production',kind:'production',status:'done',steps:1000}]}
  const errors=[]; page.on('pageerror', e=>errors.push(e.message))
  let frame=[],keys=[]
  // Suppress workspace autosave: the source is a read-only visualization input.
  await page.route('**/api/design/save-workspace', route => route.fulfill({json:{identity_disposition:'confirmed'}}))
  await page.route(/\/api\/oxdna\/jobs(?:\?.*)?$/,r=>r.fulfill({json:[job]}))
  await page.route(`**/api/oxdna/jobs/${job.job_id}`,r=>r.fulfill({json:job}))
  await page.route('**/api/simulate/jobs**',r=>r.fulfill({json:[{...job,engine:'oxdna',kind:'run'}]}))
  await page.route('**/api/jobs/active',r=>r.fulfill({json:{jobs:[]}}))
  await page.route(`**/api/oxdna/jobs/${job.job_id}/**`,r=>{
    const url=new URL(r.request().url()), endpoint=url.pathname.split('/').at(-1)
    const stages=[{name:'production',kind:'production',n_frames:2}]
    if(endpoint==='trajectory-meta')return r.fulfill({json:{ready:true,n_frames:2,n_nucleotides:keys.length,markers:[],stages}})
    if(endpoint==='trajectory' || endpoint==='trajectory-bin') {
      const start=Number(url.searchParams.get('frame_start') || 0),end=Math.min(1,Number(url.searchParams.get('frame_end')??1)),count=end-start+1
      const header=Buffer.from(JSON.stringify({ready:true,n_frames:count,n_nucleotides:keys.length,keys,stages,markers:[],frame_start:start,total_n_frames:2}))
      if(endpoint==='trajectory') {
        const offset=(12+header.length+3)&~3,body=Buffer.alloc(offset+frame.length*count*4)
        body.write('NADOTR1\0');body.writeUInt32LE(header.length,8);header.copy(body,12)
        for(let i=0;i<count;i++)frame.forEach((v,k)=>body.writeFloatLE(v,offset+(i*frame.length+k)*4))
        return r.fulfill({contentType:'application/octet-stream',body})
      }
      const compact=frame.filter((_,i)=>i%9<6),offset=(20+header.length+3)&~3,body=Buffer.alloc(offset+compact.length*count*4)
      ;[0x4E54524A,1,count,keys.length,header.length].forEach((v,i)=>body.writeUInt32LE(v,i*4));header.copy(body,20)
      for(let i=0;i<count;i++)compact.forEach((v,k)=>body.writeFloatLE(v,offset+(i*compact.length+k)*4))
      return r.fulfill({contentType:'application/octet-stream',body})
    }
    if(endpoint==='display')return r.fulfill({json:{ready:true,positions:[],nanoparticles:design.nanoparticles.map(p=>({id:p.id,pose:p.pose.values}))}})
    if(endpoint.endsWith('progress'))return r.fulfill({json:{active:false}})
    return r.fulfill({json:{ready:false}})
  })
  let previewDownloads=0
  page.on('request',r=>{if(r.url().includes('/trajectory-bin'))previewDownloads++})
  try {
    await page.setViewportSize({width:1100,height:800})
    await page.addInitScript(()=>Object.defineProperty(window,'devicePixelRatio',{get:()=>.5}))
    await page.goto('/?doc=__e2e__em-trajectory&open=Plasmonic_test.nadoc&open-type=design')
    await page.waitForFunction(()=>window.__nadocTest?.store.getState().currentGeometry?.length)
    await page.evaluate(()=>window.__nadocTest.setRepresentation('cylinders'))
    // Keep gold and EM visible; prevent per-frame FEM updates from re-enabling
    // dense DNA in software WebGL. Coordinates and simulation motion stay live.
    // The override lives only in this disposable test page.
    await page.evaluate(()=>{
      const renderer=window.__nadocTest.getDesignRenderer(),setVisible=renderer.setDesignVisible.bind(renderer)
      renderer.setDesignVisible=()=>setVisible(false)
      setVisible(false)
    })
    const geometry=await page.evaluate(()=>window.__nadocTest.store.getState().currentGeometry)
    keys=geometry.map(n=>[n.helix_id,n.bp_index,n.direction,n.copy??0])
    frame=geometry.flatMap(n=>[...n.backbone_position,...n.base_normal,...n.axis_tangent])
    for (const [i,p] of design.nanoparticles.entries()) {
      keys.push(['__gold__',i]);const v=p.pose.values
      frame.push(v[3],v[7],v[11],v[0],v[4],v[8],v[2],v[6],v[10])
    }
    // Rail clicks add columns; free space before opening Simulations.
    for (const side of ['left','right']) {
      const close = page.locator(`#${side}-panel .sidebar-close:visible`)
      while (await close.count()) await close.first().click()
    }
    await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
    await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
    await page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`).click()
    const card=page.locator('#oxdna-jobs-viz-body')
    if (!await card.isVisible()) await page.locator('#oxdna-jobs-viz-toggle').click()
    await expect(card.locator('[data-em-settings]')).toHaveAttribute('title','Setting')
    await expect(card.locator('[data-em-trajectory]')).toHaveAttribute('title','this will perform EM analysis based on what is in the current settings (see gear)')
    await card.locator('[data-em-settings]').click()
    await page.locator('#em-analysis-panel [data-shell]').selectOption('none')
    await page.locator('#em-analysis-panel [data-resolution]').selectOption('25')
    await page.locator('#em-analysis-panel [data-close]').click()
    await page.locator('#oxdna-jobs-traj-full-toggle').check()
    await expect(card.locator('[data-em-trajectory]')).toBeVisible({timeout:30000})
    // Loading forces Full and restores DNA visibility; hide only that dense mesh
    // again. Gold, its simulated poses and the EM overlay remain rendered.
    await page.evaluate(()=>window.__nadocTest.getDesignRenderer().setDesignVisible(false))
    await card.locator('[data-em-trajectory]').click()
    const confirmation=page.getByRole('dialog',{name:'EM trajectory analysis'})
    await expect(confirmation).toContainText('all 2 selected trajectory frames')
    await expect(confirmation).toHaveClass(/modal--sm/)
    await expect(confirmation.getByRole('button',{name:'Continue',exact:true})).toHaveClass(/btn--primary/)
    const box=await confirmation.boundingBox()
    expect(Math.abs(box.x+box.width/2-550)).toBeLessThan(3)
    expect(Math.abs(box.y+box.height/2-400)).toBeLessThan(3)
    await page.getByRole('dialog').getByRole('button',{name:'Cancel',exact:true}).click()
    await card.locator('[data-em-trajectory]').click()
    let releaseFirst, blockedFirst = true
    const firstGate = new Promise(resolve=>{releaseFirst=resolve})
    await page.route('**/api/em-analysis/trajectories/*/frames/0',async route=>{
      if (blockedFirst) { blockedFirst=false; await firstGate }
      await route.continue().catch(()=>{})
    })
    const started=page.waitForResponse(r=>r.url().endsWith('/api/em-analysis/trajectories')&&r.request().method()==='POST')
    await page.getByRole('dialog').getByRole('button',{name:'Continue',exact:true}).click()
    const response=await started;expect(response.ok()).toBe(true);pendingBatch=(await response.json()).id
    await expect(card.locator('[data-em-status]')).toContainText('2/2 loaded frames',{timeout:60000})
    await page.evaluate(()=>window.__nadocTest.getDesignRenderer().setDesignVisible(false))
    // A stalled field for frame zero must not hold up a seek to frame one.
    await page.locator('#oxdna-jobs-traj-slider').fill('1')
    await page.waitForFunction(()=>window.__nadocTest.scene.children.some(o=>o.name==='experimental-em-field'&&o.children.some(c=>c.isPoints)))
    releaseFirst()
    const restored = page.waitForResponse(r=>r.url().endsWith(`/em-analysis/trajectories/${pendingBatch}/frames/0`) && r.status()===200)
    await page.locator('#oxdna-jobs-traj-slider').fill('0')
    await restored
    await expect(card.locator('[data-em-frame-status]')).toHaveText('')
    await expect(page.locator('#oxdna-jobs-traj-slider').locator('..').locator('.em-trajectory-progress')).toHaveAttribute('aria-valuenow','100')
    await expect(page.locator('#oxdna-jobs-traj-interpolate')).toBeEnabled()
    await expect(page.locator('#oxdna-jobs-traj-interpolate')).toBeChecked()
    // Both volumes were fetched ahead: returning to a frame requires no HTTP request.
    let frameRequests=0
    page.on('request',r=>{if(r.url().includes(`/em-analysis/trajectories/${pendingBatch}/frames/`))frameRequests++})
    await page.locator('#oxdna-jobs-traj-slider').fill('1')
    await page.locator('#oxdna-jobs-traj-slider').fill('0')
    expect(frameRequests).toBe(0)
    await page.locator('#oxdna-jobs-traj-play').click()
    try {
      await page.waitForFunction(()=>window.__nadocTest.scene.children.some(o=>o.name==='experimental-em-field' && o.userData.interpolation > 0 && o.userData.interpolation < 1),null,{timeout:15000})
    } catch(error) {
      console.log('EM_PLAYBACK_STATE',await page.evaluate(()=>({
        play:document.querySelector('#oxdna-jobs-traj-play')?.outerHTML,
        frame:document.querySelector('#oxdna-jobs-traj-label')?.textContent,
        status:document.querySelector('#oxdna-jobs-viz-body [data-em-frame-status]')?.textContent,
        smooth:document.querySelector('#oxdna-jobs-traj-interpolate')?.checked,
        fields:window.__nadocTest.scene.children.filter(o=>o.name==='experimental-em-field').map(o=>o.userData),
      })))
      throw error
    }
    await expect(card.locator('[data-em-frame-status]')).toContainText('visual interpolation')
    await page.locator('#oxdna-jobs-traj-play').click()
    await expect(card.locator('[data-em-frame-status]')).toHaveText('')
    // Exercise the Appearance PNG command with the analyzed simulation still active.
    await page.locator('.left-tab-btn[data-tab="photo"]').click()
    await page.locator('#photo-lighting-enabled').check()
    await page.evaluate(()=>window.__photoMode.setExportSize(320,240))
    const png=page.waitForEvent('download')
    await page.locator('#photo-export-btn').evaluate(button=>button.click())
    const download=await png
    expect(download.suggestedFilename()).toContain('320x240.png')
    expect(await download.failure()).toBeNull()
    await page.waitForFunction(()=>window.__nadocTest.scene.children.some(o=>o.name==='experimental-em-field' && o.userData.sampleCount>0))
    await page.locator('#photo-lighting-enabled').uncheck()
    await card.locator('[data-em-toggle]').uncheck()
    await expect(page.locator('#oxdna-jobs-traj-interpolate')).toBeEnabled()
    expect(previewDownloads).toBe(0) // both preview frames were already loaded in the nine-value page
    expect(errors).toEqual([])
  } finally {
    if (errors.length) console.log('EM_TRAJECTORY_ERRORS', errors)
    expect(hash(await readFile(source))).toBe(hash(raw))
  }
})
