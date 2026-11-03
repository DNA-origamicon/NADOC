import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Real display controller/renderers with a deterministic, displaced paused frame.
// Only job transport is stubbed; annotation edits and saves use the actual UI/API.
test('annotation edits preserve a paused oxDNA trajectory and its atomistic display', async ({ page }) => {
  test.setTimeout(120000)
  await page.setViewportSize({width:1600,height:1000})
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__annotation-pose', name: 'annotation-pose' })
  const fixture = await page.evaluate(() => {
    const nucs = window.__nadocTest.store.getState().currentGeometry
    const atoms = nucs.map((n, serial) => ({ serial, element:'C', name:'C', helix_id:n.helix_id,
      bp_index:n.bp_index, direction:n.direction, strand_id:n.strand_id,
      x:n.backbone_position[0], y:n.backbone_position[1], z:n.backbone_position[2] }))
    const keys = nucs.map(n => [n.helix_id,n.bp_index,n.direction,n.copy_k ?? 0])
    const frame = nucs.flatMap(n => [n.backbone_position[0]+8,n.backbone_position[1],n.backbone_position[2],1,0,0])
    const xyz = atoms.flatMap(a => [a.x+8,a.y,a.z])
    return { atoms, keys, frame, xyz }
  })
  await page.route('**/api/oxdna/jobs/__e2e__annotation-pose/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('-bin')) return route.fulfill({ body: Buffer.alloc(0) })
    if (path.endsWith('/atomistic-display-bundle') || path.endsWith('/atomistic-model'))
      return route.fulfill({ json:{ atoms:fixture.atoms, bonds:[], bonds_available:false } })
    if (path.endsWith('/frames-atomistic')) return route.fulfill({ json:{ '0':fixture.xyz } })
    return route.fulfill({ json:{ ready:true } })
  })
  await page.evaluate(async fixture => {
    const display=window.__nadocOxdnaDisplay
    await display.loadFullTrajectoryPage('__e2e__annotation-pose', { keys:fixture.keys, frames:[fixture.frame] })
    window.__nadocTest.setRepresentation('ballstick')
    await display.reapplyForRepr()
  },fixture)
  const state = () => page.evaluate(() => {
    const t=window.__nadocTest, positions=[]
    t.getAtomisticRenderer().visitAtoms((atom,pos)=>positions.push([pos.x,pos.y,pos.z]))
    return { positions, cgVisible:t.isCGVisible(),
      active:window.__nadocOxdnaDisplay.isActive(), info:window.__nadocOxdnaDisplay.trajectoryInfo() }
  })
  await expect.poll(async () => (await state()).positions.length).toBe(fixture.atoms.length)
  await expect.poll(async () => (await state()).cgVisible).toBe(false)
  const before=await state()
  expect(before.positions[0][0]).toBeCloseTo(fixture.atoms[0].x+8,4)
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const column=page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await column.locator('.anno-add').click()
  const card=column.locator('.anno-card').first()
  await card.locator('[data-field="text"]').fill('Paused frame annotation')
  await expect.poll(async () => (await state()).cgVisible).toBe(false)
  // Zoom into a recognizable run of simulated atoms for pixel verification.
  await page.evaluate(positions => {
    const center=positions.slice(0,20).reduce((a,p)=>a.map((v,i)=>v+p[i]/20),[0,0,0])
    window.__nadocTest.applyCameraPoseForTest({position:center.map(v=>v+5),target:center,up:[0,0,1]})
  }, before.positions)
  // Compare the WebGL canvas itself, so DOM callout edits cannot mask a pose reset.
  await page.waitForTimeout(300)
  await page.mouse.move(0,0)
  const capture=()=>page.locator('#canvas').screenshot({ style: '.nadoc-anno-layer { visibility:hidden!important }' })
  const imageBefore=await capture()
  const response=page.waitForResponse(r=>r.url().endsWith('/design/annotations') && r.request().method()==='PUT')
  await card.locator('[data-field="text"]').fill('Edited without moving the trajectory')
  await response
  await card.locator('[data-field="color"]').fill('#ff0000')
  await card.locator('[data-field="highlight"]').check()
  await card.locator('[data-field="highlightType"]').selectOption('silhouette')
  await column.locator('[data-field="enabled"]').uncheck()
  await page.waitForTimeout(300)
  expect(await state()).toEqual(before)
  await page.mouse.move(0,0)
  expect((await capture()).equals(imageBefore)).toBe(true)
  if(process.env.NADOC_E2E_SHOT) await page.screenshot({path:process.env.NADOC_E2E_SHOT})
  // Negative control: explicitly restoring native display must move the model.
  await page.evaluate(()=>window.__nadocOxdnaDisplay.stopAndRestore())
  await expect.poll(async()=>JSON.stringify((await state()).positions)).not.toBe(JSON.stringify(before.positions))
  expect(errors,errors.join('\n')).toEqual([])
})
