// Display-only fixture: no molecular documents or persisted jobs. The existing
// teardown/reporter removes the session and screenshot artifacts after review.
import {test,expect} from '@playwright/test'
test('umbrella results from right-click and metrics button',async({page},info)=>{
 test.setTimeout(90000)
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/?doc=__e2e__umbrella-results')
 await page.waitForFunction(()=>!!window.__nadocTest)
 await page.evaluate(async()=>{
  const {umbrellaResultActions}=await import('/src/ui/oxdna_umbrella_results.js')
  const {createContextMenu}=await import('/src/ui/primitives/index.js')
  const {initOxdnaMetricsCard}=await import('/src/ui/oxdna_metrics_card.js')
  window.umbrellaJob={job_id:'display-fixture',design_name:'Duplex VMMC',run_config:{vmmc_melting:{},vmmc_result:{status:'inconclusive',tm_c:70,replica_tm_sem_c:1,temperatures_c:[60,70,80],duplex_yield:[.9,.5,.1],reasons:['More sampling needed.'],sampling_temperature_c:70,salt_concentration_M:.3,box_conditions:{concentration_uM:26.5686},replicas:[{tm_c:null,yields:[.8,.4,.05],visited_pair_counts:1,observed_bound_unbound_transitions:0,recorded_samples:2001,pair_counts:[0,1,2],biased_counts:[100,0,0],biased_occupancy:[1,0,0],unbiased_probability:[1,0,0]}]}}}
  const row=document.createElement('button');row.textContent='VMMC display fixture';row.id='umbrella-fixture-row';row.style='position:fixed;top:100px;left:100px;z-index:100';document.body.append(row)
  row.oncontextmenu=e=>{e.preventDefault();createContextMenu({x:e.clientX,y:e.clientY,items:umbrellaResultActions(window.umbrellaJob)})}
  // Use the actual metrics-card factory with the selected fixture result.
  const card=document.getElementById('oxdna-metrics-card');document.body.append(card);card.style='display:block;position:fixed;left:100px;top:160px;z-index:100;background:#161b22;max-height:200px;overflow:auto'
  window.umbrellaMetrics=initOxdnaMetricsCard({getSelectedJob:()=>window.umbrellaJob,getJobs:()=>[window.umbrellaJob]})
 })
 await page.locator('#umbrella-fixture-row').click({button:'right'})
 await page.getByText('View results',{exact:true}).last().click()
 const dialog=page.locator('.oxdna-umbrella-results')
 await expect(dialog).toBeVisible()
 await expect(dialog).toContainText('70.00 °C')
 await expect(dialog.getByRole('img')).toBeVisible()
 await expect(dialog).toContainText('Recorded transitions')
 await dialog.getByText('Replica 1 · base-pair sampling',{exact:true}).click()
 await expect(dialog).toContainText('Histogram visits')
 expect(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true)
 await page.waitForTimeout(250)
 await page.screenshot({path:info.outputPath('umbrella-results.png')})
 await page.setViewportSize({width:720,height:900})
 expect(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true)
 await page.screenshot({path:info.outputPath('umbrella-results-narrow.png')})
 await page.setViewportSize({width:1280,height:720})
 await page.keyboard.press('Escape')
 await expect(dialog).toHaveCount(0)
 await page.locator('#oxdna-metrics-card').getByRole('button',{name:'View results',exact:true}).click()
 await expect(dialog).toContainText('More sampling needed.')
 const [download]=await Promise.all([page.waitForEvent('download'),dialog.getByRole('button',{name:'Export analysis JSON'}).click()])
 expect(download.suggestedFilename()).toBe('vmmc-display-fixture.json')
 await dialog.getByRole('button',{name:'Close',exact:true}).click()
 await page.evaluate(()=>{window.umbrellaJob={job_id:'ordinary',run_config:{}};window.umbrellaMetrics.refresh()})
 await expect(page.locator('#oxdna-metrics-card').getByRole('button',{name:'View results',exact:true})).toHaveCount(0)
 expect(errors).toEqual([])
 if(process.env.NADOC_UMBRELLA_REVIEW){console.log('UMBRELLA_REVIEW',info.outputPath(''));await page.waitForTimeout(45000)}
})
