import { expect, test } from '@playwright/test'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`
const JOB_ID = process.env.NADOC_E2E_OCC_BASE_JOB || '2d8b40a0d507'
const DESIGN = '/home/jojo/Work/NADOC/workspace/2hb_2xT.nadoc'

test('occupancy works for one and multiple ordinary and crossover-extra bases', async ({ page, request }) => {
  test.setTimeout(300_000)
  const jr = await request.get(`${API}/oxdna/jobs/${JOB_ID}`).catch(() => null)
  test.skip(!jr?.ok(), `oxDNA job ${JOB_ID} is not present`)

  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.evaluate(async path => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.querySelectorAll('.left-tab-btn').forEach(b => { b.disabled = false })
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    const client = await import('/src/api/client.js')
    await client.loadDesign(path)
  }, DESIGN)
  await page.click('#left-tab-strip [data-tab="dynamics"]').catch(() => {})
  await expect(page.locator('#oxdna-jobs-body')).toBeVisible()

  await page.evaluate(() => {
    const all = document.getElementById('oxdna-jobs-show-all')
    if (all && !all.checked) {
      all.checked = true
      all.dispatchEvent(new Event('change', { bubbles: true }))
    }
  })
  await expect.poll(() => page.evaluate(id =>
    !!document.querySelector(`#oxdna-jobs-list [data-job-id="${id}"]`), JOB_ID)).toBe(true)
  await page.evaluate(id =>
    document.querySelector(`#oxdna-jobs-list [data-job-id="${id}"]`).click(), JOB_ID)

  const toggle = page.locator('#oxdna-jobs-occupancy-toggle')
  await expect(toggle).toBeEnabled()
  await toggle.check()
  await expect.poll(() => page.locator('#oxdna-jobs-occupancy-status').textContent(),
    { timeout: 120_000 }).toMatch(/configurations, revisited|Drift, not switching|Single configuration/)
  await page.locator('#oxdna-jobs-occupancy-scope').selectOption('selection')

  const baseKeys = await page.evaluate(() => {
    const d = window.__nadocTest.store.getState().currentDesign
    const h = d.helices[0].id
    return [`${h}:10:FORWARD`, `${h}:11:FORWARD`]
  })

  const runScope = async keys => {
    await page.evaluate(() => document.getElementById('oxdna-occupancy-scope-clear').click())
    await page.evaluate(picked => window.__nadocTest.store.setState({
      multiSelectedBaseKeys: picked, selectedObject: null,
    }), keys)
    const responsePromise = page.waitForResponse(r =>
      r.url().includes(`/oxdna/jobs/${JOB_ID}/occupancy`) && r.request().method() === 'POST')
    await page.locator('#oxdna-occupancy-scope-add').click()
    const response = await responsePromise
    const body = await response.json()
    await expect.poll(() => page.locator('#oxdna-jobs-occupancy-status').textContent(),
      { timeout: 120_000 }).toMatch(/configurations, revisited|Drift, not switching|Single configuration/)
    return { status: response.status(), body }
  }

  const single = await runScope(baseKeys.slice(0, 1))
  expect(single.status).toBe(200)
  expect(single.body).toMatchObject({ ready: true, scoped: true, n_selected: 1 })

  const multiple = await runScope(baseKeys)
  expect(multiple.status).toBe(200)
  expect(multiple.body).toMatchObject({ ready: true, scoped: true, n_selected: 2 })

  const xbKeys = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign
    .crossovers.filter(x => x.extra_bases?.length)
    .slice(0, 2).map(x => `__xb__:${x.id}:0`))
  expect(xbKeys).toHaveLength(2)

  const singleXb = await runScope(xbKeys.slice(0, 1))
  expect(singleXb.status).toBe(200)
  expect(singleXb.body).toMatchObject({ ready: true, scoped: true, n_selected: 1 })

  const multipleXb = await runScope(xbKeys)
  expect(multipleXb.status).toBe(200)
  expect(multipleXb.body).toMatchObject({ ready: true, scoped: true, n_selected: 2 })

  // Do not let teardown pass vacuously before the asynchronous ghost builder has drawn
  // anything. Confirm the cloud actually owns and hides the design scene first.
  await expect.poll(() => page.evaluate(() => window.__nadocOccupancy.stats()),
    { timeout: 30_000 }).toMatchObject({ states: 2, visible: true, owningScene: true })

  // Off must tear down both the real rank-0 medoid and all ghost states. Repeat it on a
  // cached whole-structure re-toggle, where display setup can finish after the radio is
  // already off (the race that originally left states visible).
  const off = page.locator('#oxdna-jobs-viz-off')
  // Reproduce the stale-radio form of the bug: Off already LOOKS selected, so a second
  // radio check has no change event. A real user click must still be a teardown action.
  await off.evaluate(el => { el.checked = true })
  await expect.poll(() => page.evaluate(() => window.__nadocOccupancy.stats().states)).toBe(2)
  await off.click()
  await expect.poll(() => page.evaluate(() => ({
    occupancy: window.__nadocOccupancy.stats(),
    cgVisible: window.__nadocTest.isCGVisible(),
  }))).toMatchObject({
    occupancy: { states: 0, owningScene: false },
    cgVisible: true,
  })
  await page.locator('#oxdna-jobs-occupancy-scope').selectOption('all')
  await toggle.check()
  await off.check()
  await expect.poll(() => page.evaluate(() => {
    let ghosts = 0
    window.__nadocScene.traverse(o => { if (o.name?.startsWith('occupancyGhost')) ghosts++ })
    return { mode: window.__nadocOxdnaDisplay?.mode?.() ?? null, ghosts }
  })).toEqual({ mode: null, ghosts: 0 })
  await expect(toggle).not.toBeChecked()

  // Switching straight to a peer visualization must perform the same occupancy teardown
  // as Off. Exercise the cached/in-flight edge too: radio handlers run after the browser
  // has already unchecked Occupancy, and display mode may not be published yet.
  await toggle.check()
  await page.locator('#oxdna-jobs-flex-toggle').check()
  await expect.poll(() => page.evaluate(() => {
    let ghosts = 0
    window.__nadocScene.traverse(o => { if (o.name?.startsWith('occupancyGhost')) ghosts++ })
    return { mode: window.__nadocOxdnaDisplay?.mode?.() ?? null, ghosts }
  }), { timeout: 120_000 }).toEqual({ mode: 'rmsf', ghosts: 0 })
  await expect(toggle).not.toBeChecked()
  expect(errors).toEqual([])
})
