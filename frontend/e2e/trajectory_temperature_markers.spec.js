// Read-only existing design; mocked jobs/trajectories, no native job or saved design.
// __e2e__ session cache disabled; screenshots and credentials removed by global teardown/reporters.
import { expect, test } from '@playwright/test'

test('trajectory temperature ticks show the following frame range on hover', async ({page}, info) => {
  test.setTimeout(120000)
  const job = {job_id:'__e2e__temperature-markers', parent_job_id:'__e2e__relax',
    design_source_path:'2hb_1xT.nadoc',design_name:'2hb_1xT',status:'completed',backend:'CPU',created_at:1,
    current_stage_idx:3,run_config:{kind:'run',thermal_ramp:{start_c:25,end_c:35,step_c:5}},
    stages:[1,2,3].map(i=>({name:`${i}_thermal`,kind:'production',status:'done',steps:1000000}))}
  const markers=[25,30,35].map((t,i)=>({frame:i*3,end_frame:i*3+2,temperature_c:t,kind:'production',label:'→ production',stage_name:`${i+1}_thermal`}))
  const stages=markers.map(m=>({name:m.stage_name,kind:'production',n_frames:3,temperature_c:m.temperature_c}))
  let frame=[], keys=[]
  await page.route(/\/api\/oxdna\/jobs(?:\?.*)?$/, r=>r.fulfill({json:[job]}))
  await page.route(`**/api/oxdna/jobs/${job.job_id}`, r=>r.fulfill({json:job}))
  await page.route('**/api/simulate/jobs**',r=>r.fulfill({json:[{...job,engine:'oxdna',kind:'run'}]}))
  await page.route('**/api/jobs/active',r=>r.fulfill({json:{jobs:[]}}))
  await page.route(`**/api/oxdna/jobs/${job.job_id}/**`, r=>{
    const url=new URL(r.request().url()), endpoint=url.pathname.split('/').at(-1)
    if(endpoint==='trajectory-meta')return r.fulfill({json:{ready:true,n_frames:9,n_nucleotides:keys.length,markers,stages}})
    if(endpoint==='trajectory-bin'){
      const start=Number(url.searchParams.get('frame_start') || 0), end=Math.min(8,Number(url.searchParams.get('frame_end') ?? 8))
      const step=Number(url.searchParams.get('frame_step') || 1), count=Math.floor((end-start)/step)+1
      const header=Buffer.from(JSON.stringify({keys,markers,stages,frame_start:start,frame_step:step,total_n_frames:9}))
      const compact=frame.filter((_,i)=>i%9<6), offset=(20+header.length+3)&~3
      const body=Buffer.alloc(offset+compact.length*count*4)
      ;[0x4E54524A,1,count,keys.length,header.length].forEach((v,i)=>body.writeUInt32LE(v,i*4))
      header.copy(body,20)
      for(let i=0;i<count;i++)compact.forEach((v,k)=>body.writeFloatLE(v,offset+(i*compact.length+k)*4))
      return r.fulfill({contentType:'application/octet-stream',body})
    }
    if(endpoint==='trajectory'){
      const start=Number(url.searchParams.get('frame_start') || 0)
      const end=Math.min(8,Number(url.searchParams.get('frame_end') ?? 8)), count=end-start+1
      const header=Buffer.from(JSON.stringify({ready:true,n_frames:count,frame_start:start,total_n_frames:9,n_nucleotides:keys.length,keys,markers,stages}))
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
  await page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`).click()
  if (!await page.locator('#oxdna-jobs-traj-full-toggle').isVisible()) await page.locator('#oxdna-jobs-viz-toggle').click()
  await page.locator('#oxdna-jobs-traj-full-toggle').check({timeout:15000})
  const ticks=page.locator('#oxdna-jobs-traj-markers [data-temperature-c]')
  await expect(ticks).toHaveCount(3).catch(async error => {
    console.log('TRAJECTORY_STATUS', await page.locator('#oxdna-jobs-traj-status').textContent())
    throw error
  })
  const middle=ticks.nth(1)
  await middle.hover()
  await expect(middle.getByRole('tooltip')).toBeVisible()
  expect(await middle.getByRole('tooltip').evaluate(node=>node.matches(':popover-open'))).toBe(true)
  await expect(middle.getByRole('tooltip')).toContainText('30 °C — target temperature from frame 4 through 6')
  await expect(page.locator('#oxdna-jobs-traj-status')).not.toContainText('incomplete')
  await middle.focus()
  await expect(middle).toBeFocused()
  if(process.env.NADOC_TEMPERATURE_VISUAL_REVIEW){
    await page.setViewportSize({width:1440,height:1000})
    await middle.hover()
    await page.screenshot({path:info.outputPath('temperature-marker-hover.png')})
    console.log('TEMPERATURE_VISUAL_READY',info.outputPath('temperature-marker-hover.png'))
    await page.waitForTimeout(45000)
  }
  await page.locator('#oxdna-jobs-traj-slider').fill('5')
  await expect(page.locator('#oxdna-jobs-traj-slider')).toHaveValue('5')
})
