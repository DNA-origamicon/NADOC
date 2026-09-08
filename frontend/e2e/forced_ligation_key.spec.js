/**
 * Forced ligation via the NORMAL end multi-select + 'i' key/context menu — interactive
 * gesture e2e (HARD-tier, on the shared scene-harness).
 *
 * What the vitest unit tests + smoke gate CANNOT cover: the REAL user gestures —
 * engage the End selection level, multi-select a 5′ end and a 3′ end (via a
 * ctrl-drag LASSO, or a plain-click then Ctrl-click — all feed canonical End refs),
 * press 'i' or right-click an endpoint → the strands merge via /design/forced-ligation,
 * driven end-to-end through selection_manager + the main.js shortcut wiring.
 *
 * Fixture: a 200-bp auto-scaffolded helix, nicked at two visible interior
 * positions so an opposite-polarity cross-strand end pair renders on-screen (past
 * cylinder-LOD) for the gesture.
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, rightClickVerifiedEnd, selectEndsForLigation } from './helpers/scene_harness.js'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000') + '/api'

// Build the fixture: a fresh auto-scaffolded helix, nicked at two visible interior
// positions. Returns { doc, H, before } (before = the pre-ligation design).
async function setupNickedScaffold(page, tag) {
  const doc = `__e2e__forcedlig-${tag}-${Date.now()}`
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name: `forcedlig-${tag}` })
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(400)

  // On-screen bp window (real raycast identity at each visible bead).
  const visible = await page.evaluate(() => {
    const out = []
    for (const p of window.__nadocTest.getBackboneBeadScreenPositions(500)) {
      const h = window.__nadocTest.pickBeadAt(p.x, p.y)
      if (h && typeof h.bp_index === 'number') out.push(h.bp_index)
    }
    return [...new Set(out)].sort((a, b) => a - b)
  })
  expect(visible.length, 'several beads visible past cylinder-LOD').toBeGreaterThanOrEqual(4)

  // Nick two visible INTERIOR positions (never a strand tip — nicking an end is a
  // no-op/error). Key only on OCCUPIED nucleotides (geometry may carry both
  // directions per bp; nicking the unoccupied one fails).
  const geom = await (await page.request.get(`${API}/design/geometry`, { headers: H })).json()
  const byBp = new Map(geom.nucleotides.filter(n => n.strand_id).map(n => [n.bp_index, n]))
  const nickable = visible.filter(bp => { const n = byBp.get(bp); return n && !n.is_five_prime && !n.is_three_prime })
  expect(nickable.length, 'interior (non-tip) visible positions to nick').toBeGreaterThanOrEqual(2)
  const wanted = [nickable[Math.floor(nickable.length * 0.25)], nickable[Math.floor(nickable.length * 0.75)]]
  let nicked = 0
  for (const bp of wanted) {
    const n = byBp.get(bp)
    const r = await page.request.post(`${API}/design/nick`, {
      data: { helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction }, headers: H,
    })
    if (r.ok()) nicked++
  }
  expect(nicked, 'at least one interior nick landed').toBeGreaterThanOrEqual(1)
  // Rebuild the tab's scene from the mutated backend design.
  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: d })
    bc.close()
  }, doc)
  await page.waitForTimeout(700)

  const before = (await (await page.request.get(`${API}/design`, { headers: H })).json()).design
  expect(before.strands.length, 'nicking created multiple strands').toBeGreaterThanOrEqual(2)
  return { doc, H, before }
}

async function fetchDesign(page, H) {
  return (await (await page.request.get(`${API}/design`, { headers: H })).json()).design
}

async function setupTwoHelixScaffolds(page, tag) {
  const doc = `__e2e__forcedlig-${tag}-${Date.now()}`
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name: `forcedlig-${tag}` })
  const initial = await fetchDesign(page, H)
  const firstId = initial.helices[0].id
  await page.request.post(`${API}/design/helix-at-cell`, {
    data: { row: 0, col: 1, length_bp: 200 }, headers: H,
  })
  const withSecond = await fetchDesign(page, H)
  const secondId = withSecond.helices.find(helix => helix.id !== firstId).id
  await page.request.post(`${API}/design/scaffold-domain-paint`, {
    data: { helix_id: secondId, lo_bp: 0, hi_bp: 199 }, headers: H,
  })
  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: d })
    bc.close()
  }, doc)
  await page.waitForTimeout(800)
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(400)
  const before = await fetchDesign(page, H)
  expect(before.strands.length, 'one scaffold strand per helix').toBe(2)
  return { H, before }
}

test.describe('Forced ligation — selected 5′/3′ ends', () => {
  // The scene-harness boot (loadScaffoldedPart: build + auto-scaffold + first
  // WebGL render) can race on a cold throwaway backend; retry so a boot flake
  // doesn't mask the gesture assertion (which is deterministic once booted).
  test.describe.configure({ retries: 2, timeout: 45_000 })

  test('LASSO a 5′ and a 3′ end at End level, press i → strands merge into one', async ({ page }) => {
    const { H, before } = await setupTwoHelixScaffolds(page, 'lasso')
    const flBefore = (before.forced_ligations ?? []).length

    const sel = await selectEndsForLigation(page)
    expect(sel.count, `two opposite-polarity ends selected via lasso: ${JSON.stringify(sel.diagnostics)}`).toBe(2)
    const arcsBefore = await page.evaluate(() => window.__nadocTest.getRenderedCrossoverArcCount())
    await page.keyboard.press('i')
    await page.waitForTimeout(800)

    const after = await fetchDesign(page, H)
    expect((after.forced_ligations ?? []).length, 'a forced ligation was recorded').toBe(flBefore + 1)
    expect(after.strands.length, 'the two selected strands merged into one').toBe(before.strands.length - 1)
    const arcsAfter = await page.evaluate(() => window.__nadocTest.getRenderedCrossoverArcCount())
    expect(arcsAfter, 'the cross-helix ligation arc is present without reload').toBe(arcsBefore + 1)
  })

  test('right-click either member of a selected pair → Force ligate menu → merge', async ({ page }) => {
    const { H, before } = await setupNickedScaffold(page, 'context')
    const flBefore = (before.forced_ligations ?? []).length

    const sel = await selectEndsForLigation(page)
    expect(sel.count, `two opposite-polarity ends selected: ${JSON.stringify(sel.diagnostics)}`).toBe(2)
    await rightClickVerifiedEnd(page, sel.five)
    const action = page.getByText('Force ligate', { exact: true })
    await expect(action).toBeVisible()
    await action.click()
    await page.waitForTimeout(800)

    const after = await fetchDesign(page, H)
    expect((after.forced_ligations ?? []).length, 'a forced ligation was recorded').toBe(flBefore + 1)
    expect(after.strands.length, 'the two selected strands merged into one').toBe(before.strands.length - 1)
  })
})
