import { expect, test } from '@playwright/test'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`
const JOB_ID = process.env.NADOC_E2E_MD_OCC_TEARDOWN_JOB || '029a76c6a59f'
const DESIGN = '/home/jojo/Work/NADOC/workspace/2hb_2xT.nadoc'

test('MD occupancy render inventory returns to baseline after Off', async ({ page, request }, testInfo) => {
  test.setTimeout(600_000)
  const jr = await request.get(`${API}/md/jobs/${JOB_ID}`).catch(() => null)
  test.skip(!jr?.ok(), `MD job ${JOB_ID} is not present`)

  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.evaluate(async path => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    document.querySelectorAll('.left-tab-btn').forEach(b => { b.disabled = false })
    await (await import('/src/api/client.js')).loadDesign(path)
  }, DESIGN)
  await page.locator('#left-tab-strip [data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await expect(page.locator('#md-jobs-occupancy-toggle')).toBeVisible()
  await page.evaluate(() => {
    const all = document.getElementById('md-jobs-show-all')
    if (all && !all.checked) {
      all.checked = true
      all.dispatchEvent(new Event('change', { bubbles: true }))
    }
  })
  await expect.poll(() => page.evaluate(id =>
    !!document.querySelector(`#md-jobs-list [data-job-id="${id}"]`), JOB_ID),
  { timeout: 60_000 }).toBe(true)
  await page.evaluate(id =>
    document.querySelector(`#md-jobs-list [data-job-id="${id}"]`).click(), JOB_ID)

  const toggle = page.locator('#md-jobs-occupancy-toggle')
  await expect(toggle).toBeEnabled({ timeout: 30_000 })
  const before = await page.evaluate(() => window.__nadocRenderAudit.capture())
  await testInfo.attach('before-native.png', {
    body: await page.locator('#canvas').screenshot(), contentType: 'image/png',
  })
  await toggle.check()
  await expect.poll(() => page.evaluate(() => window.__nadocOccupancy.stats()),
    { timeout: 300_000 }).toMatchObject({ states: 2, owningScene: true })
  const during = await page.evaluate(() => window.__nadocRenderAudit.capture())
  await testInfo.attach('during-occupancy.png', {
    body: await page.locator('#canvas').screenshot(), contentType: 'image/png',
  })
  expect(during.visibleOccupancyRenderables).toBeGreaterThan(0)

  await page.locator('#md-jobs-viz-off').click()
  await expect.poll(() => page.evaluate(() => ({
    stats: window.__nadocOccupancy.stats(),
    mode: window.__nadocMdViz.mode(),
    audit: window.__nadocRenderAudit.capture(),
    cgVisible: window.__nadocTest.isCGVisible(),
  })), { timeout: 30_000 }).toMatchObject({
    stats: { states: 0, owningScene: false },
    mode: null,
    audit: { visibleOccupancyRenderables: 0 },
    cgVisible: true,
  })
  const after = await page.evaluate(() => window.__nadocRenderAudit.capture())
  await testInfo.attach('after-off.png', {
    body: await page.locator('#canvas').screenshot(), contentType: 'image/png',
  })
  const comparison = await page.evaluate(([a, b, c]) =>
    window.__nadocRenderAudit.compare(a, b, c), [before, during, after])
  expect(comparison.occupancyVisibleAfter).toBe(0)
  expect(comparison.leftAfter).toEqual([])
  await testInfo.attach('render-object-comparison.json', {
    body: Buffer.from(JSON.stringify(comparison, null, 2)), contentType: 'application/json',
  })

  // Drive real scoped POSTs through the MD card. This is the route that previously sent
  // a Pydantic selection object into the cache signature and failed for every element.
  await page.locator('#md-jobs-occupancy-scope').selectOption('selection')
  const keys = await page.evaluate(() => {
    const d = window.__nadocTest.store.getState().currentDesign
    const h = d.helices[0].id
    const xb = d.crossovers.filter(x => x.extra_bases?.length)
      .slice(0, 2).map(x => `__xb__:${x.id}:0`)
    return { base: `${h}:10:FORWARD`, xb }
  })
  expect(keys.xb).toHaveLength(2)

  const runScope = async selected => {
    await page.evaluate(() => document.getElementById('md-occupancy-scope-clear').click())
    await page.evaluate(picked => window.__nadocTest.store.setState({
      multiSelectedBaseKeys: picked, selectedObject: null,
    }), selected)
    const responsePromise = page.waitForResponse(r =>
      r.url().includes(`/md/jobs/${JOB_ID}/occupancy`) && r.request().method() === 'POST')
    await page.locator('#md-occupancy-scope-add').click()
    const response = await responsePromise
    const body = await response.json()
    expect(response.status()).toBe(200)
    expect(body.ready, body.reason || 'scoped MD occupancy was not ready').toBe(true)
    return body
  }

  await toggle.check()
  expect((await runScope([keys.base])).n_selected).toBe(1)
  expect((await runScope(keys.xb)).n_selected).toBe(2)
  expect((await runScope([keys.base, ...keys.xb])).n_selected).toBe(3)
  await page.locator('#md-jobs-viz-off').click()

  // Peer visualizations own the same model and must invoke the same occupancy teardown.
  await page.locator('#md-jobs-occupancy-scope').selectOption('all')
  await toggle.check()
  await expect.poll(() => page.evaluate(() => window.__nadocOccupancy.stats().states),
    { timeout: 30_000 }).toBe(2)
  await page.locator('#md-jobs-flex-toggle').check()
  await expect.poll(() => page.evaluate(() => ({
    mode: window.__nadocMdViz.mode(),
    occupancy: window.__nadocOccupancy.stats(),
    audit: window.__nadocRenderAudit.capture(),
  })), { timeout: 120_000 }).toMatchObject({
    mode: 'rmsf',
    occupancy: { states: 0, owningScene: false },
    audit: { visibleOccupancyRenderables: 0 },
  })
})
