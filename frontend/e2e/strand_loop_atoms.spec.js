/** Isolated workspace only; __e2e__ document/history cleanup is global-teardown. */
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

test('insertion loop renders in every atomistic mode and Detail Surface', async ({ page, request }, testInfo) => {
  test.setTimeout(120000)
  const errors = trackConsoleErrors(page), responses = []
  page.on('response', r => { if (r.url().includes('/api/') && r.status() >= 400) responses.push(`${r.status()} ${r.url()}`) })
  const api = process.env.NADOC_E2E_API_BASE, doc = '__e2e__loop_atomistic'
  const headers = { 'X-NADOC-Doc': doc }
  const bundle = await request.post(`${api}/api/design/bundle`, { headers, data: {
    name: doc, cells: [[0,0]], length_bp: 42, lattice_type: 'HONEYCOMB', ligate_adjacent: false,
  } })
  expect(bundle.ok()).toBe(true)
  const design = (await (await request.get(`${api}/api/design`, { headers })).json()).design
  const strand = design.strands.find(s => s.strand_type === 'scaffold'), domain = strand.domains[0]
  expect((await request.post(`${api}/api/design/strand-loop`, { headers, data: {
    strand_id: strand.id, helix_id: domain.helix_id, bp_index: 20, direction: domain.direction,
    length: 30, aspect_ratio: 3, rotation_deg: 0,
  } })).ok()).toBe(true)
  await page.goto(`/?doc=${doc}&readiness=simulation`)
  await page.waitForFunction(() => window.__nadocTest?.getDesignRenderer()?.getBackboneEntries()?.some(e => e.nuc.loop_order > 0))
  const simulationSidebar = page.getByRole('button', { name: 'Close Simulations sidebar', exact: true })
  if (await simulationSidebar.isVisible()) await simulationSidebar.click()
  await page.evaluate(() => {
    const t = window.__nadocTest, entries = t.getDesignRenderer().getBackboneEntries().map(e => e.nuc)
    const loop = entries.filter(n => n.loop_order > 0), anchor = entries.find(n => n.strand_id === loop[0].strand_id && n.bp_index === loop[0].bp_index && !n.loop_order)
    const center = [0,1,2].map(i => loop.reduce((sum,n) => sum+n.backbone_position[i],0)/loop.length)
    const side = [-anchor.base_normal[1], anchor.base_normal[0], .1]
    t.applyCameraPoseForTest({target:center,position:center.map((v,i)=>v+side[i]*22),up:[0,0,1]})
  })
  await page.locator('#menu-seq-assign-scaffold').evaluate(el => el.click())
  const target = page.getByLabel('Scaffold sequence target', { exact: true })
  await page.locator('.modal__overlay').filter({ has: target }).getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(target).toBeHidden()
  for (const button of await page.locator('.sidebar-close').all()) {
    if (await button.isVisible()) await button.click()
  }
  await page.waitForTimeout(250)
  await page.screenshot({ path: testInfo.outputPath('loop-full.png') })
  for (const mode of ['ballstick', 'vdw', 'stick']) {
    await page.locator(`#menu-view-atomistic-${mode}`).evaluate(el => el.click())
    await page.waitForFunction(mode => window.__nadocTest.getAtomisticRenderer().getMode() === mode, mode)
    await expect.poll(() => page.evaluate(() => {
      const copies = new Set()
      window.__nadocTest.getAtomisticRenderer().visitAtoms(atom => { if (atom.copy_k > 0) copies.add(atom.copy_k) })
      return copies.size
    })).toBe(30)
    await page.locator('.toast [aria-label="Dismiss"]').evaluateAll(buttons => buttons.forEach(button => button.click()))
    await page.waitForTimeout(250)
    await page.screenshot({ path: testInfo.outputPath(`loop-${mode}.png`) })
  }
  const surfaceResponse = page.waitForResponse(r => /\/api\/design\/surface(?:-bin)?\?/.test(r.url()))
  await page.locator('#menu-view-surface-detail').evaluate(el => el.click())
  expect((await surfaceResponse).ok()).toBe(true)
  await page.waitForFunction(() => {
    if (window.__nadocTest.getAtomisticRenderer().getMode() !== 'off') return false
    let visible = false
    window.__nadocTest.scene.traverse(o => { if (/surface/i.test(o.name) && o.isMesh && o.geometry?.attributes?.position?.count > 0) { let p = o; while (p && p.visible) p = p.parent; if (!p) visible = true } })
    return visible
  })
  await page.waitForTimeout(400)
  await page.screenshot({ path: testInfo.outputPath('loop-detail-surface.png') })
  expect(responses).toEqual([])
  expect(errors).toEqual([])
})
