/**
 * Assembly overhang hover + click selection → Overhangs Manager prefill.
 *
 * New model (no selectable button): in assembly mode, hovering within a medium
 * radius of an overhang shows its label transiently; clicking it adds it to the
 * ordered selection (green ring + persistent label) and prefills the Overhangs
 * Manager's Side A / Side B on open. The "show all overhang labels" toggle still
 * shows every label.
 *
 * Builds an assembly with two file-backed Arm.nadoc instances (labeled
 * overhangs), separated in space for two unambiguous targets.
 *
 * Requires the shared renderer (default) so window.__NADOC_DBG__ is set.
 * Uses the Playwright-configured isolated API backend.
 */

import { test, expect } from '@playwright/test'

const API    = process.env.NADOC_E2E_API_BASE ?? 'http://127.0.0.1:8002'
const MODE   = '#mode-indicator'
const NASS   = 'OverhangSelTest'   // stem; file is OverhangSelTest.nass
const SOURCE = 'Arm.nadoc'         // workspace design with labeled overhangs

const xform = (tx) => ({ values: [1,0,0,tx, 0,1,0,0, 0,0,1,0, 0,0,0,1] })

// Projected on-screen anchors + per-instance representatives, label-sprite ids,
// and ring count — all read from the live scene via __NADOC_DBG__.
const SCENE_PROBE = `(() => {
  const dbg = window.__NADOC_DBG__
  const { camera } = dbg
  const canvas = document.getElementById('canvas')
  const rect = canvas.getBoundingClientRect()
  const anchors = (dbg.assemblyRenderer.getOverhangAnchors?.() ?? []).map(a => {
    const v = a.world.clone().project(camera)
    return {
      instanceId: a.instanceId, overhangId: a.overhangId, label: a.label,
      sx: rect.left + (v.x*0.5+0.5)*rect.width,
      sy: rect.top + (-v.y*0.5+0.5)*rect.height,
      on: v.z > -1 && v.z < 1,
    }
  })
  const labels = []
  dbg.scene.traverse(o => { if (o.parent?.name === 'sharedOverhangNames' && o.userData?.tag === 'overhang-name')
    labels.push({ instanceId: o.userData.instanceId, overhangId: o.userData.overhangId }) })
  let rings = 0
  dbg.scene.traverse(o => { if (o.name === 'overhangSelHighlight') rings = o.children.length })
  return { anchors, labels, rings, rect: { l: rect.left, t: rect.top, r: rect.right, b: rect.bottom } }
})()`

test('hover shows a label, click selects (ring + persistent label) and prefills the manager', async ({ page, request }) => {
 test.setTimeout(90_000)
 try {
  // ── Build + save the assembly via API ───────────────────────────────────────
  expect((await request.post(`${API}/api/assembly`)).status()).toBe(201)
  for (const [name, tx] of [['Arm 1', 0], ['Arm 2', 70]]) {
    const r = await request.post(`${API}/api/assembly/instances`, {
      data: { source: { type: 'file', path: SOURCE }, name, transform: xform(tx) },
    })
    expect(r.status()).toBe(201)
  }
  expect((await request.post(`${API}/api/assembly/save`, { data: { filename: NASS } })).ok()).toBeTruthy()

  // ── Open it through the library UI ──────────────────────────────────────────
  await page.goto('/')
  await page.waitForTimeout(800)
  const row = page.locator('.lib-row-name', { hasText: NASS }).first()
  await row.waitFor({ state: 'visible', timeout: 10_000 })
  await row.click()
  await expect(page.locator(MODE)).toContainText('ASSEMBLY', { timeout: 20_000 })
  await page.waitForFunction(
    () => !document.getElementById('file-load-progress')?.classList.contains('visible'),
    { timeout: 10_000 },
  )

  // No overhang selectable button in assembly mode — the whole section is hidden.
  expect(await page.evaluate(() => getComputedStyle(document.getElementById('select-filter')).display))
    .toBe('none')

  // Wait until the renderer has overhang anchors on ≥2 instances.
  await page.waitForFunction(() => {
    const a = window.__NADOC_DBG__?.assemblyRenderer.getOverhangAnchors?.() ?? []
    return new Set(a.map(x => x.instanceId)).size >= 2
  }, { timeout: 15_000 })

  // ── One representative on-screen anchor per instance ─────────────────────────
  const probe0 = await page.evaluate(SCENE_PROBE)
  expect(probe0.labels.length, 'no labels shown initially (toggle off, nothing hovered/selected)').toBe(0)
  const byInst = new Map()
  for (const a of probe0.anchors) if (a.on && !byInst.has(a.instanceId)) byInst.set(a.instanceId, a)
  const reps = [...byInst.values()]
  console.log('[reps]', JSON.stringify(reps.map(r => ({ inst: r.instanceId.slice(0,6), sx: Math.round(r.sx), sy: Math.round(r.sy) }))))
  expect(reps.length, 'a representative anchor on two instances').toBeGreaterThanOrEqual(2)
  const [cA, cB] = reps
  expect(Math.hypot(cA.sx - cB.sx, cA.sy - cB.sy), 'representatives separated on screen').toBeGreaterThan(20)
  const corner = { x: probe0.rect.l + 5, y: probe0.rect.t + 5 }   // far from centred parts

  // ── Hover reveals a transient label for that instance ────────────────────────
  // Assembly overhang picking is an explicit tool, shared with the visible
  // toolbar's `ovhg` action and its O keyboard shortcut.
  await page.keyboard.press('o')
  await expect.poll(() => page.evaluate(
    () => window.__NADOC_DBG__.store.getState().toolFilters?.overhangLocations,
  )).toBe(true)
  await page.mouse.move(cA.sx, cA.sy)
  await page.waitForTimeout(200)
  let p = await page.evaluate(SCENE_PROBE)
  console.log('[hover A] labels=', JSON.stringify(p.labels))
  expect(p.labels.some(l => l.instanceId === cA.instanceId), 'hovering shows instance A label').toBe(true)
  expect(await page.evaluate(() => window.__NADOC_DBG__.store.getState().assemblyOverhangSelection.length),
    'hover does not select').toBe(0)

  // Move away → transient label disappears.
  await page.mouse.move(corner.x, corner.y)
  await page.waitForTimeout(200)
  p = await page.evaluate(SCENE_PROBE)
  expect(p.labels.length, 'label clears when cursor leaves the overhang').toBe(0)

  // ── Click selects: green ring + persistent label, into Side A ────────────────
  await page.mouse.click(cA.sx, cA.sy)
  await page.waitForTimeout(200)
  let sel = await page.evaluate(() => window.__NADOC_DBG__.store.getState().assemblyOverhangSelection)
  const activeAfterA = await page.evaluate(() => window.__NADOC_DBG__.store.getState().activeInstanceId)
  console.log('[click A] sel=', JSON.stringify(sel))
  expect(sel.length, 'one overhang selected').toBe(1)
  expect(sel[0].instanceId).toBe(cA.instanceId)
  expect(activeAfterA, 'clicking an overhang selects it, not the part').toBeNull()
  p = await page.evaluate(SCENE_PROBE)
  expect(p.rings, 'one green ring for the selection').toBe(1)
  expect(p.labels.some(l => l.instanceId === sel[0].instanceId && l.overhangId === sel[0].overhangId),
    'selected overhang has a label').toBe(true)

  // Move away → selected label PERSISTS (only the selected one shows).
  await page.mouse.move(corner.x, corner.y)
  await page.waitForTimeout(200)
  p = await page.evaluate(SCENE_PROBE)
  expect(p.labels.length, 'only the selected label persists after moving away').toBe(1)
  expect(p.labels[0].overhangId).toBe(sel[0].overhangId)

  // ── Click a second overhang → Side B ─────────────────────────────────────────
  await page.mouse.click(cB.sx, cB.sy)
  await page.waitForTimeout(200)
  sel = await page.evaluate(() => window.__NADOC_DBG__.store.getState().assemblyOverhangSelection)
  console.log('[click B] sel=', JSON.stringify(sel))
  expect(sel.length, 'two overhangs selected').toBe(2)
  expect(sel[1].instanceId).toBe(cB.instanceId)
  expect(`${sel[0].instanceId}|${sel[0].overhangId}`).not.toBe(`${sel[1].instanceId}|${sel[1].overhangId}`)
  expect((await page.evaluate(SCENE_PROBE)).rings, 'two rings now').toBe(2)

  // ── Clicking a non-overhang clears the selection ─────────────────────────────
  await page.mouse.click(corner.x, corner.y)
  await page.waitForTimeout(200)
  expect(await page.evaluate(() => window.__NADOC_DBG__.store.getState().assemblyOverhangSelection.length),
    'clicking empty space clears the overhang selection').toBe(0)
  p = await page.evaluate(SCENE_PROBE)
  expect(p.rings, 'rings cleared').toBe(0)
  expect(p.labels.length, 'persistent labels cleared').toBe(0)

  // Re-select the two overhangs for the remaining manager check.
  await page.mouse.click(cA.sx, cA.sy)
  await page.waitForTimeout(150)
  await page.mouse.click(cB.sx, cB.sy)
  await page.waitForTimeout(150)
  sel = await page.evaluate(() => window.__NADOC_DBG__.store.getState().assemblyOverhangSelection)
  expect(sel.length, 're-selected two overhangs').toBe(2)

  // ── "Show all overhang labels" toggle still shows every label ────────────────
  // (Tested before opening the manager, whose modal overlay covers the strip.)
  await page.locator('#view-tools [data-vt="overhangNames"]').click()
  await page.waitForTimeout(300)
  p = await page.evaluate(SCENE_PROBE)
  const totalAnchors = (await page.evaluate(() => window.__NADOC_DBG__.assemblyRenderer.getOverhangAnchors().length))
  console.log('[show all] labels=', p.labels.length, 'anchors=', totalAnchors)
  expect(p.labels.length, 'show-all renders every overhang label').toBe(totalAnchors)
  // Turn it back off so it doesn't affect later expectations.
  await page.locator('#view-tools [data-vt="overhangNames"]').click()
  await page.waitForTimeout(200)

  // ── Open the Overhangs Manager → Side A / Side B prefilled to match ──────────
  await page.evaluate(() => document.getElementById('menu-assembly-overhangs-manager')?.click())
  await page.waitForTimeout(600)
  const selA = page.locator('#aohc-list-a .ct-selected-a')
  const selB = page.locator('#aohc-list-b .ct-selected-b')
  await expect(selA, 'Side A prefilled').toHaveCount(1)
  await expect(selB, 'Side B prefilled').toHaveCount(1)
  expect(await selA.first().getAttribute('data-overhang-id')).toBe(sel[0].overhangId)
  expect(await selB.first().getAttribute('data-overhang-id')).toBe(sel[1].overhangId)
 } finally {
  await request.delete(`${API}/api/library/file`, { params: { path: `${NASS}.nass` } }).catch(() => {})
 }
})
