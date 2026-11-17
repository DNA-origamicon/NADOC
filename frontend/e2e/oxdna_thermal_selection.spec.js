// Read-only existing design; mocked jobs/trajectories, no native job or saved design.
// __e2e__ session cache disabled; screenshots and credentials removed by global teardown/reporters.
import { expect, test } from '@playwright/test'

test('wizard creates a Tm tree whose parent and children load the requested temperatures', async ({page}, info) => {
  test.setTimeout(120000)
  const job = {job_id:'__e2e__temperature-markers', parent_job_id:'__e2e__relax',
    design_source_path:'2hb_1xT.nadoc',design_name:'2hb_1xT',status:'queued',backend:'CPU',created_at:3,
    current_stage_idx:0,run_config:{kind:'run',thermal_ramp:{start_c:25,end_c:35,step_c:5}},
    stages:[1,2,3].map(i=>({name:`${i}_thermal`,kind:'production',status:'pending',steps:1000000}))}
  const parent={...job,job_id:'__e2e__relax',parent_job_id:null,created_at:1,status:'completed',run_config:{kind:'relax'},stages:[{name:'3_equil',kind:'equil',status:'done'}]}
  const ordinary={...parent,job_id:'__e2e__ordinary',parent_job_id:parent.job_id,created_at:2,run_config:{kind:'run'}}
  const jobs=[parent,ordinary], scopes=[], payloads=[]
  await page.route(`**/api/oxdna/jobs/${parent.job_id}/run`, async r=>{
    const body=r.request().postDataJSON(); payloads.push(body)
    expect(body.backend).toBe('CUDA')
    expect(body.thermal_ramp).toMatchObject({start_c:25,end_c:35,step_c:5,block_steps:10000000})
    job.run_config={kind:'run',...body}; jobs.push(job)
    await r.fulfill({json:job})
  })
  await page.route('**/estimate-run-disk',r=>r.fulfill({json:{warn:false,free_bytes:1e12,predicted_bytes:1024,free_after_bytes:1e12}}))
  const markers=[25,30,35].map((t,i)=>({frame:i*3,end_frame:i*3+2,temperature_c:t,kind:'production',label:'→ production',stage_name:`${i+1}_thermal`}))
  const stages=markers.map(m=>({name:m.stage_name,kind:'production',n_frames:3,temperature_c:m.temperature_c}))
  let frame=[], keys=[]
  await page.route(/\/api\/oxdna\/jobs(?:\?.*)?$/, r=>r.fulfill({json:jobs}))
  await page.route(`**/api/oxdna/jobs/${job.job_id}`, r=>r.fulfill({json:job}))
  await page.route('**/api/simulate/jobs**',r=>r.fulfill({json:jobs.map(j=>({...j,engine:'oxdna',kind:j.parent_job_id?'run':'relax'}))}))
  await page.route('**/api/jobs/active',r=>r.fulfill({json:{jobs:[]}}))
  await page.route(`**/api/oxdna/jobs/${job.job_id}/**`, r=>{
    const url=new URL(r.request().url()), endpoint=url.pathname.split('/').at(-1)
    const scope=url.searchParams.get('scope')
    if(endpoint.startsWith('trajectory') && !endpoint.endsWith('progress'))scopes.push(scope)
    const selected=scope?.startsWith('thermal:')?markers.filter(m=>m.stage_name===scope.slice(8)):markers
    const activeMarkers=selected.map((m,i)=>({...m,frame:i*3,end_frame:i*3+2}))
    const activeStages=selected.map(m=>stages.find(s=>s.name===m.stage_name)), total=activeStages.length*3
    if(endpoint==='trajectory-meta')return r.fulfill({json:{ready:true,n_frames:total,n_nucleotides:keys.length,markers:activeMarkers,stages:activeStages}})
    if(endpoint==='trajectory-bin'){
      const start=Number(url.searchParams.get('frame_start') || 0), end=Math.min(total-1,Number(url.searchParams.get('frame_end') ?? total-1))
      const step=Number(url.searchParams.get('frame_step') || 1), count=Math.floor((end-start)/step)+1
      const header=Buffer.from(JSON.stringify({keys,markers:activeMarkers,stages:activeStages,frame_start:start,frame_step:step,total_n_frames:total}))
      const compact=frame.filter((_,i)=>i%9<6), offset=(20+header.length+3)&~3
      const body=Buffer.alloc(offset+compact.length*count*4)
      ;[0x4E54524A,1,count,keys.length,header.length].forEach((v,i)=>body.writeUInt32LE(v,i*4))
      header.copy(body,20)
      for(let i=0;i<count;i++)compact.forEach((v,k)=>body.writeFloatLE(v,offset+(i*compact.length+k)*4))
      return r.fulfill({contentType:'application/octet-stream',body})
    }
    if(endpoint==='trajectory'){
      const start=Number(url.searchParams.get('frame_start') || 0)
      const end=Math.min(total-1,Number(url.searchParams.get('frame_end') ?? total-1)), count=end-start+1
      const header=Buffer.from(JSON.stringify({ready:true,n_frames:count,frame_start:start,total_n_frames:total,n_nucleotides:keys.length,keys,markers:activeMarkers,stages:activeStages}))
      const offset=(12+header.length+3)&~3, body=Buffer.alloc(offset+frame.length*count*4)
      body.write('NADOTR1\0');body.writeUInt32LE(header.length,8);header.copy(body,12)
      for(let i=0;i<count;i++)frame.forEach((v,k)=>body.writeFloatLE(v,offset+(i*frame.length+k)*4))
      return r.fulfill({contentType:'application/octet-stream',body})
    }
    if(endpoint==='display')return r.fulfill({json:{ready:true,positions:[]}})
    if(endpoint.endsWith('progress'))return r.fulfill({json:{active:false}})
    return r.fulfill({json:{ready:false}})
  })
  await page.goto('/?doc=__e2e__temperature-markers&open=2hb_1xT.nadoc&open-type=design')
  await page.waitForFunction(()=>window.__nadocTest?.store.getState().currentGeometry?.length)
  const geometry=await page.evaluate(()=>window.__nadocTest.store.getState().currentGeometry)
  keys=geometry.map(n=>[n.helix_id,n.bp_index,n.direction,n.copy??0])
  frame=geometry.flatMap(n=>[...n.backbone_position,...n.base_normal,...n.axis_tangent])
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await page.locator('#oxdna-jobs-new-btn').click()
  const wizard=page.locator('.modal--oxdna-wizard')
  await wizard.locator('.wizard-mode',{hasText:'Production'}).click()
  await wizard.getByLabel('Continue from').selectOption(parent.job_id)
  await expect(wizard.getByLabel('Execution backend')).toHaveValue('CUDA')
  await wizard.locator('[data-thermal-field="enabled"]').check()
  if (process.env.NADOC_CPD_GPU_VISUAL === '1') {
    await page.screenshot({path:info.outputPath('gpu-thermal-wizard.png')})
    await page.waitForTimeout(30000)
  }
  await wizard.locator('[data-thermal-field="end_c"]').fill('35')
  await wizard.locator('[data-thermal-field="end_c"]').press('Tab')
  await wizard.locator('.wizard-tab',{hasText:'Summary'}).click()
  await wizard.getByRole('button',{name:'Create job',exact:true}).click({timeout:15000})
  await expect(wizard).toBeHidden()
  expect(payloads).toHaveLength(1)
  const row=page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`)
  const group=page.locator('#simulate-jobs-list .thermal-job-group').filter({has:page.locator(`[data-job-id="${job.job_id}"]`)})
  await expect(row).toContainText('Tm Run 2')
  await expect(row.locator('.nadoc-spinner')).toHaveCount(1)
  await group.locator('.thermal-job-toggle').click()
  await expect(group.getByRole('button',{name:/25C - Run 2/})).toBeVisible()
  await expect(group.locator('.thermal-job-state .nadoc-spinner')).toHaveCount(3)
  await group.getByRole('button',{name:/25C - Run 2/}).click()
  await expect(page.locator('#oxdna-jobs-traj-full-toggle')).toBeDisabled()
  job.status='running';job.stages[0].status='done';job.stages[1].status='running';job.current_stage_idx=1
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed')))
  await expect(group.locator('[data-status="completed"]')).toHaveCount(1)
  await expect(group.locator('[data-status="running"]')).toHaveCount(1)
  job.status='failed';job.stages[1].status='failed'
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed')))
  await expect(group.locator('[data-status="failed"]')).toHaveCount(1)
  await expect(row.locator('[title="Failed"]')).toHaveCount(1)
  job.status='completed';job.stages.forEach(s=>s.status='done');job.current_stage_idx=3
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed')))
  await expect(group.locator('[data-status="completed"]')).toHaveCount(3)
  await row.click()
  if (!await page.locator('#oxdna-jobs-traj-full-toggle').isVisible()) await page.locator('#oxdna-jobs-viz-toggle').click()
  await page.locator('#oxdna-jobs-traj-full-toggle').check({timeout:15000})
  const ticks=page.locator('#oxdna-jobs-traj-markers [data-temperature-c]')
  await expect(ticks).toHaveCount(3).catch(async error => {
    console.log('TRAJECTORY_STATUS', await page.locator('#oxdna-jobs-traj-status').textContent())
    throw error
  })
  expect(scopes).toContain('thermal')
  await expect(page.locator('#oxdna-jobs-traj-slider')).toHaveAttribute('max','8')
  await group.getByRole('button',{name:/30C - Run 2/}).click()
  await expect(group.getByRole('button',{name:/30C - Run 2/})).toHaveAttribute('aria-pressed','true')
  await expect(page.locator('#oxdna-jobs-traj-controls')).toBeHidden()
  await page.locator('#oxdna-jobs-traj-full-toggle').check()
  await expect(ticks).toHaveCount(1)
  await expect(ticks.first()).toHaveAttribute('data-temperature-c','30')
  await expect(page.locator('#oxdna-jobs-traj-slider')).toHaveAttribute('max','2')
  expect(scopes).toContain('thermal:2_thermal')
  await ticks.first().hover()
  await expect(ticks.first().getByRole('tooltip')).toContainText('30 °C — target temperature from frame 1 through 3')
  if(process.env.NADOC_THERMAL_VISUAL_REVIEW){
    await page.setViewportSize({width:1440,height:1000})
    await group.scrollIntoViewIfNeeded()
    await page.screenshot({path:info.outputPath('thermal-selectable-tree.png')})
    console.log('THERMAL_SELECTION_VISUAL_READY',info.outputPath('thermal-selectable-tree.png'))
    await page.waitForTimeout(45000)
  }
  await row.click()
  await page.locator('#oxdna-jobs-traj-full-toggle').check()
  await expect(ticks).toHaveCount(3)
  await expect(page.locator('#oxdna-jobs-traj-slider')).toHaveAttribute('max','8')
})
