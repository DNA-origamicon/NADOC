import { test, expect } from '@playwright/test'
import { readFileSync, existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Read-only legacy part. Mock analysis/job endpoints create no jobs or structures.
// Only our document session may persist; afterEach removes it even after failure.
// The standard global teardown/reporter clean browser credentials and captures.
// Downloads are never saved outside Playwright; context teardown removes them on failure.
const root = fileURLToPath(new URL('../../', import.meta.url))
const source = `${root}Examples/2hb_xover_val.nadoc`
const doc = '__e2e__two-base-maps'
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

test('2-base maps capture current and next selection and show all projections', async ({page}) => {
  test.setTimeout(90000)
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  const id='__e2e__two-base-job'
  let job=null, requests=[], release
  const downloads=[]
  page.on('download',d=>downloads.push(d))
  await page.route(/\/api\/md\/jobs(?:\?.*)?$/,r=>r.fulfill({json:job?[job]:[]}))
  await page.route(`**/api/md/jobs/${id}**`,async route=>{
    const suffix=new URL(route.request().url()).pathname.split(id)[1]
    if(suffix==='/two-base-maps/progress') return route.fulfill({json:{percent:50,done:50,total:100}})
    if(suffix==='/two-base-maps') {
      const body=route.request().postDataJSON();requests.push(body)
      await new Promise(r=>{release=r})
      return route.fulfill({json:{bases:body.bases,frames:3,labels:['x (nm)','y (nm)','z (nm)','rotation x (°)','rotation y (°)','rotation z (°)'],
        rows:[[0,1,2,3,4,5],[1,2,3,4,5,6],[2,3,4,5,6,7]],note:'Relative to base 1; ring centroids and rotation vector.'}})
    }
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
    const {createSelectionController}=await import('/src/scene/selection_controller.js')
    const selection=createSelectionController({store})
    window.pickTwoBase=key=>selection.replace(key?[{kind:'base',key}]:[])
    return {id:store.getState().currentDesign.id,keys:store.getState().currentGeometry.slice(0,2).map(p=>`${p.helix_id}:${p.bp_index}:${p.direction}`)}
  },source)
  job={job_id:id,design_id:loaded.id,design_name:'2-base check',status:'completed',created_at:1,
    execution_target:'local',segments:[{name:'production',stage:'production',status:'done'}]}
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(async id=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob(id)},id)
  if(!await page.locator('#md-metrics-toggle').isVisible()) await page.locator('#md-jobs-panel-heading').click()
  if(!await page.locator('#md-two-base-1').isVisible()) await page.locator('#md-metrics-toggle').click()
  await expect(page.locator('#md-two-base-header #md-two-base-generate')).toHaveCount(1)
  await expect(page.locator('#md-two-base-header #md-two-base-show')).toHaveCount(1)
  await expect(page.locator('#md-two-base-header #md-two-base-export')).toBeDisabled()
  await expect(page.locator('#md-two-base-generate')).toBeDisabled()
  await page.evaluate(key=>window.pickTwoBase(key),loaded.keys[0])
  await page.locator('#md-two-base-1').click()
  await page.evaluate(()=>window.pickTwoBase(null))
  await page.locator('#md-two-base-2').click()
  await expect(page.locator('#md-two-base-2')).toContainText('Select a base')
  await page.evaluate(key=>window.pickTwoBase(key),loaded.keys[1])
  await expect(page.locator('#md-two-base-generate')).toBeEnabled()
  await page.locator('#md-two-base-generate').click()
  await expect(page.locator('#md-two-base-percent')).toHaveText('50%')
  await expect(page.locator('#md-two-base-progress')).toHaveAttribute('aria-valuenow','50')
  release()
  await expect(page.locator('#md-two-base-percent')).toHaveText('100%')
  await expect(page.locator('#md-two-base-show')).toBeEnabled()
  expect(requests[0]).toMatchObject({bases:loaded.keys,design_id:loaded.id})
  await page.locator('#md-two-base-show').click()
  await expect(page.locator('#two-base-maps-popup')).toBeVisible()
  await expect(page.locator('#two-base-maps-popup canvas')).toHaveCount(4)
  await expect(page.locator('#two-base-maps-popup strong')).toHaveAttribute('title',/ring centroids/)
  expect(await page.locator('#two-base-maps-popup select').evaluateAll(nodes=>nodes.map(n=>n.value))).toEqual(['0','1','12','13'])
  await page.getByLabel('Graph 1 map').selectOption('14')
  await expect(page.locator('#two-base-maps-popup canvas').first()).toHaveAttribute('aria-label', 'Rotation-vector z (°) versus Rotation-vector y (°)')
  const hasPoints=await page.locator('#two-base-maps-popup canvas').first().evaluate(canvas=>{
    const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data
    for(let i=0;i<data.length;i+=4)if(data[i+2]>data[i]+30 && data[i+2]>100)return true
    return false
  })
  expect(hasPoints).toBe(true)
  await page.keyboard.press('Escape')
  await expect(page.locator('#two-base-maps-popup')).toHaveCount(0)
  await page.locator('#md-two-base-export').click()
  await expect(page.locator('#metric-export-png')).toBeChecked()
  await page.locator('#metric-export-ok').click()
  await expect.poll(()=>downloads.length).toBe(2)
  expect(downloads.map(d=>d.suggestedFilename()).sort()).toEqual([`two_base_maps_${id}.csv`,`two_base_maps_${id}.png`])
  for(const download of downloads) await download.delete()
  expect(errors).toEqual([])
})
