/**
 * Gesture e2e: adding a primitive onto an existing part's blunt-end FACE.
 *
 * Pins the bug the user hit — clicking a blunt-end ring while a primitive is armed
 * must RETARGET the slice plane onto that face (continuation), not be swallowed by
 * the origin-plane lattice cell that sits at the same screen position. Drives the
 * REAL raycast and asserts on exposed state (__nadocTest.getSliceState).
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('blunt-end ring click retargets an armed primitive onto that face', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  const doc = 'e2e-primface'
  await loadScaffoldedPart(page, { doc, name: 'primface' })

  // Arm a primitive: Tools → Add Primitive → wait for the live (API) cards, click the
  // first beam card. Fallback cards carry no placement spec, so wait for the upgrade.
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await page.click('#menu-tools-add-primitive')
  await page.waitForSelector('#primitives-panel .primitive-card')
  await page.waitForTimeout(800)                       // let /api/primitives upgrade the list
  await page.locator('#primitives-panel .primitive-card').first().click()

  // Existing structure → origin grid is SUPPRESSED on arm; armed and waiting.
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSliceState()))
    .toMatchObject({ visible: false, placement: false, armed: true, continuation: false })

  // Find the blunt-end rings and click one until the slice plane retargets (continuation).
  const rings = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions())
  expect(rings.length, 'expected blunt-end rings on screen').toBeGreaterThan(0)

  let retargeted = false
  for (const r of rings) {
    await page.mouse.move(r.x, r.y)
    await page.waitForTimeout(60)                       // let domain_ends register the hover
    await page.mouse.down(); await page.mouse.up()
    await page.waitForTimeout(150)
    const s = await page.evaluate(() => window.__nadocTest.getSliceState())
    if (s.continuation) { retargeted = true; break }
  }
  expect(retargeted, 'ring click should retarget placement onto the face (continuation)').toBe(true)

  // Still in placement mode, now on the face.
  const s = await page.evaluate(() => window.__nadocTest.getSliceState())
  expect(s).toMatchObject({ visible: true, placement: true, continuation: true })

  // Now COMMIT: hover the face lattice + click to place the footprint as a
  // continuation. The single seed helix grows into the beam (continue + fresh).
  const H = { 'X-NADOC-Doc': doc }
  const before = await (await page.request.get('http://localhost:8000/api/design', { headers: H })).json()
  const nBefore = before.design.helices.length

  let placed = false
  const rings2 = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions())
  for (const r of (rings2.length ? rings2 : rings)) {
    await page.mouse.move(r.x, r.y); await page.waitForTimeout(60)
    await page.mouse.down(); await page.mouse.up(); await page.waitForTimeout(250)
    const after = await (await page.request.get('http://localhost:8000/api/design', { headers: H })).json()
    if (after.design.helices.length > nBefore) { placed = true; break }
  }
  expect(placed, 'committing the footprint should add helices (continuation extrude)').toBe(true)
  expect(errors, errors.join('\n')).toEqual([])
})

async function armFirstPrimitive(page) {
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await page.click('#menu-tools-add-primitive')
  await page.waitForSelector('#primitives-panel .primitive-card')
  await page.waitForTimeout(800)
  await page.locator('#primitives-panel .primitive-card').first().click()
}

test('empty workspace shows the origin grid immediately on arm', async ({ page }) => {
  const doc = 'e2e-primface-empty'
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__primface-empty')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await page.waitForTimeout(400)

  await armFirstPrimitive(page)
  // No existing structure → the origin grid appears right away.
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSliceState()))
    .toMatchObject({ visible: true, placement: true })
})

test('selecting an origin plane shows the grid on an existing structure', async ({ page }) => {
  const doc = 'e2e-primface-plane'
  await loadScaffoldedPart(page, { doc, name: 'primface-plane' })
  await armFirstPrimitive(page)
  // Suppressed until a plane is chosen…
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSliceState()))
    .toMatchObject({ visible: false, armed: true })
  // …picking a plane from the dropdown shows the origin grid.
  await page.selectOption('#primitive-plane', 'XY')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSliceState()))
    .toMatchObject({ visible: true, placement: true, continuation: false })
})

test('primitive places onto a BENT end face (deformed-frame continuation)', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  const doc = 'e2e-primface-bent'
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name: 'primface-bent' })

  // Bend the seed helix so its ends sit at deformed positions (deformed view is on
  // by default), then nudge the tab to refetch.
  const d0 = await (await page.request.get('http://localhost:8000/api/design', { headers: H })).json()
  const helixId = d0.design.helices[0].id
  const bend = await page.request.post('http://localhost:8000/api/design/deformation', {
    headers: H,
    data: { type: 'bend', plane_a_bp: 50, plane_b_bp: 150,
      params: { angle_deg: 90, direction_deg: 0 }, affected_helix_ids: [helixId], cluster_ids: [], preview: false },
  })
  expect(bend.ok(), await bend.text()).toBeTruthy()
  await page.evaluate((dc) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: dc }); bc.close()
  }, doc)
  await page.waitForTimeout(700)

  // Arm a beam primitive.
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await page.click('#menu-tools-add-primitive')
  await page.waitForSelector('#primitives-panel .primitive-card')
  await page.waitForTimeout(800)
  await page.locator('#primitives-panel .primitive-card').first().click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getSliceState()))
    .toMatchObject({ visible: false, placement: false, armed: true })

  // Click a (deformed) blunt-end ring → should retarget onto the DEFORMED face.
  const rings = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions())
  expect(rings.length).toBeGreaterThan(0)
  let onFace = false
  for (const r of rings) {
    await page.mouse.move(r.x, r.y); await page.waitForTimeout(60)
    await page.mouse.down(); await page.mouse.up(); await page.waitForTimeout(150)
    const s = await page.evaluate(() => window.__nadocTest.getSliceState())
    if (s.continuation && s.deformed) { onFace = true; break }
  }
  expect(onFace, 'ring click should retarget onto the deformed face (continuation + deformed)').toBe(true)

  // Commit → deformed-frame continuation grows the helix count.
  const before = await (await page.request.get('http://localhost:8000/api/design', { headers: H })).json()
  const nBefore = before.design.helices.length
  let placed = false
  const rings2 = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions())
  for (const r of (rings2.length ? rings2 : rings)) {
    await page.mouse.move(r.x, r.y); await page.waitForTimeout(60)
    await page.mouse.down(); await page.mouse.up(); await page.waitForTimeout(250)
    const after = await (await page.request.get('http://localhost:8000/api/design', { headers: H })).json()
    if (after.design.helices.length > nBefore) { placed = true; break }
  }
  expect(placed, 'committing on a bent face should add helices (deformed continuation)').toBe(true)
  expect(errors, errors.join('\n')).toEqual([])
})
