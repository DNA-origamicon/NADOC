import { test, expect } from '@playwright/test'
import { readFileSync, existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Read-only legacy part. Mock analysis/job endpoints create no jobs or structures.
// Only our document session may persist; afterEach removes it even after failure.
// The standard global teardown/reporter clean browser credentials and captures.
const root = fileURLToPath(new URL('../../', import.meta.url))
const source = `${root}Examples/2hb_xover_val.nadoc`
const doc = '__e2e__uv-crosslinking'
const session = `${root}workspace/.session/${doc}`
let original
test.beforeEach(() => { expect(existsSync(session)).toBe(false); original=readFileSync(source) })
test.afterEach(async ({ page,request }) => {
  try {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api/documents/${doc}`)
  } finally {
    rmSync(session,{force:true,recursive:true})
    expect(existsSync(session)).toBe(false)
    expect(readFileSync(source).equals(original)).toBe(true)
  }
})

test('unified UV controls recolor native geometry locally and pause/reload cleanly', async ({page}) => {
  test.setTimeout(90000)
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  const id='__e2e__uv-job'
  let job=null, sites=[], calls=0, pauseCalls=0, hold=false, release
  await page.route(/\/api\/md\/jobs(?:\?.*)?$/,r=>r.fulfill({json:job?[job]:[]}))
  await page.route(`**/api/md/jobs/${id}**`,async route=>{
    const suffix=new URL(route.request().url()).pathname.split(id)[1]
    if(suffix==='/photoproduct-likelihood') {
      calls++
      if(hold) await new Promise(r=>{release=r})
      return route.fulfill({json:{ready:true,complete:true,sites,n_sampled_frames:100,n_total_frames:100,
        note:'Geometric opportunity, not calibrated yield.',pairs:[
          {a:0,b:1,chemistry:'TC',same_strand:false,opportunity:.2,min_distance_ang:3.5},
          {a:0,b:2,chemistry:'TT',same_strand:true,opportunity:.1,min_distance_ang:3.8,tt_contact_mean:.2},
        ]}}).catch(()=>{})
    }
    if(suffix==='/analysis/cancel') { pauseCalls++; return route.fulfill({json:{cancelled:1}}) }
    if(suffix==='/photoproduct-progress') return route.fulfill({json:{active:true,fraction:.3,done:30,total:100,message:'Progress saved'}})
    return route.fulfill({json:suffix===''?job:{ready:false}})
  })
  await page.goto(`/?debug=1&doc=${doc}`)
  await page.waitForFunction(()=>window.__nadocTest&&window.__nadocMdPanel)
  const loaded=await page.evaluate(async source=>{
    const api=await import('/src/api/client.js')
    await api.loadDesign(source)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden','hidden')
    document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b=>{b.disabled=false})
    window.__leftSidebar?.refresh?.()
    const {store}=await import('/src/state/store.js')
    return {id:store.getState().currentDesign.id,geometry:store.getState().currentGeometry}
  },source)
  sites=loaded.geometry.slice(0,3).map((p,i)=>({id:`D:${i}`,label:`Base ${i}`,display_key:`${p.helix_id}:${p.bp_index}:${p.direction}`}))
  job={job_id:id,design_id:loaded.id,design_name:'UV check',status:'completed',created_at:1,
    execution_target:'local',segments:[{name:'production',stage:'production',status:'done'}]}
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(async id=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob(id)},id)
  if(!await page.locator('#md-jobs-viz-toggle').isVisible()) await page.locator('#md-jobs-panel-heading').click()
  if(!await page.locator('#md-jobs-photoproduct-toggle').isVisible()) await page.locator('#md-jobs-viz-toggle').click()
  await expect(page.locator('#md-jobs-weld-toggle')).toHaveCount(0)
  await expect(page.locator('#md-jobs-uv-options')).not.toBeVisible()
  await expect(page.locator('#md-jobs-uv-note, #md-jobs-uv-pairs')).toHaveCount(0)
  await expect(page.locator('#md-jobs-photoproduct-option')).toHaveAttribute('title', /geometric opportunity/)
  await expect(page.locator('#md-metrics-toggle')).toHaveAttribute('title', /selected NAMD run/)
  const toggle=page.locator('#md-jobs-photoproduct-toggle')
  await toggle.check()
  await expect(page.locator('#md-jobs-photoproduct-status')).toContainText('Saved analysis')
  await expect(page.locator('#md-jobs-uv-interstrand')).toBeChecked()
  await expect(page.locator('#md-jobs-uv-intrastrand')).toBeChecked()
  await expect(page.locator('#md-jobs-uv-tt-only')).not.toBeChecked()
  expect(await page.evaluate(()=>window.__nadocTest.getDesignRenderer().getFemPositions())).toBeNull()
  await expect(page.locator('#flex-scale')).toBeVisible()
  await page.locator('#flex-scale-max').fill('0.3')
  await page.locator('#flex-scale-max').press('Enter')
  await page.locator('#md-jobs-uv-tt-only').check()
  expect(calls).toBe(1)
  let coloring=await page.evaluate(()=>window.__nadocMdViz.coloringInfo())
  expect(coloring.hi).toBeCloseTo(.3)
  expect(coloring.values.map(v=>v.value)).toEqual([.1,0,.1])
  await page.locator('#md-jobs-uv-intrastrand').uncheck()
  expect((await page.evaluate(()=>window.__nadocMdViz.coloringInfo())).values.every(v=>v.value===0)).toBe(true)
  await page.locator('#md-jobs-viz-off').check()
  await expect(page.locator('#md-jobs-uv-options')).not.toBeVisible()
  await toggle.check()
  await expect(page.locator('#md-jobs-photoproduct-status')).toContainText('Saved analysis')
  expect(calls).toBe(2)
  await page.locator('#md-jobs-viz-off').check()
  hold=true
  await toggle.check()
  await expect.poll(()=>calls).toBe(3)
  await page.locator('#md-jobs-viz-off').check()
  await expect.poll(()=>pauseCalls).toBeGreaterThan(0)
  hold=false;release()
  await toggle.check()
  await expect(page.locator('#md-jobs-photoproduct-status')).toContainText('Saved analysis')
  expect(await page.evaluate(()=>window.__nadocTest.getDesignRenderer().getFemPositions())).toBeNull()
  expect(errors).toEqual([])
})
