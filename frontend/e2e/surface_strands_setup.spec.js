/**
 * Surface capture-strand setup card → 3D.
 *
 * Pins two contracts that silently broke in Aug 2026, both because the card injects
 * synthetic nucleotides straight into the CG renderer via a FULL design rebuild:
 *
 *  1. Any new mandatory field in the nucleotide record (base_position was the one that
 *     bit) throws out of that rebuild. The exception unwound through the card's own
 *     onChange, which then stopped tracking its fields — every later edit re-threw from
 *     the same stale spec and nothing in the 3D moved again, i.e. the card froze right
 *     after being opened.
 *  2. A rebuild means "the design changed" to everything downstream, but this one
 *     changes no design at all. Without an explicit restore it reverted the user's whole
 *     visualization on every keystroke: the structure snapped from its simulation frame
 *     back to NADOC native positions, the flexibility map turned back into strand
 *     colours, and every halo vanished.
 */
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000') + '/api'

/** Rendered capture-strand inventory straight off the live Three.js instances. */
const caps = (page) => page.evaluate(() => window.__nadocDR.debugCaptureRender())
const overlay = (page) => page.evaluate(() => window.__nadocSurfStrands.debug())

// Settle the 90 ms input debounce plus the rebuild it schedules.
async function settle(page) {
  await page.waitForTimeout(200)
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => r(1))))
}

/** Boot a 4-helix design, open the oxDNA Hard-surface card, enable capture strands. */
async function openSurfaceStrandsCard(page, doc) {
  const headers = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', doc)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await expect.poll(
    async () => (await page.request.get(`${API}/design`, { headers })).status(),
    { timeout: 15_000 },
  ).toBe(200)
  await page.request.post(`${API}/design/bundle`, {
    data: { cells: [[0, 0], [0, 1], [1, 0], [1, 1]], length_bp: 120, name: 'probe', plane: 'XY' },
    headers,
  })
  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: d })
    bc.close()
  }, doc)
  await page.waitForFunction(() => {
    let ok = false
    window.__nadocTest?.scene?.traverse(o => {
      if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true
    })
    return ok
  }, null, { timeout: 30_000 })

  // Hard surface is the prerequisite gate for capture strands.
  await page.click('.left-tab-btn[data-tab="dynamics"]')
  const oxBtn = page.locator('.engine-selector-btn[data-engine="oxdna"]')
  if (await oxBtn.count()) await oxBtn.click()
  await page.click('#oxdna-floor-toggle')
  await expect(page.locator('#oxdna-surfstrand-enable')).toBeDisabled()
  await page.check('#oxdna-floor-enable')
  await expect(page.locator('#oxdna-surfstrand-enable')).toBeEnabled()
  await page.check('#oxdna-surfstrand-enable')
  await page.fill('#oxdna-surfstrand-seq', 'TTTTGCTAGC')   // 10 nt
  return headers
}

test('surface-strand TransformControls are detached until a preview is actionable', async ({ page }) => {
  await page.goto('/?doc=__e2e__surfstrands_lifecycle')
  await page.waitForFunction(() => !!window.__nadocSurfStrands)
  const initial = await overlay(page)
  expect(initial.gizmoVisible).toBe(false)
  expect(initial.gizmoAttached).toBe(false)
  expect(initial.gizmoEnabled).toBe(false)

  await page.evaluate(() => window.__nadocSurfStrands.update({
    enabled: true, sequence: 'GCTA', attachEnd: "5'", shape: 'circle',
    sizeNm: 100, densityPerUm2: 1000, offsetXNm: 0, offsetYNm: 0,
    seed: 1, subjectToField: true,
  }, true))
  const active = await overlay(page)
  expect(active.gizmoVisible).toBe(true)
  expect(active.gizmoAttached).toBe(true)
  expect(active.gizmoEnabled).toBe(true)

  await page.evaluate(() => window.__nadocSurfStrands.clear())
  const cleared = await overlay(page)
  expect(cleared.gizmoVisible).toBe(false)
  expect(cleared.gizmoAttached).toBe(false)
  expect(cleared.gizmoEnabled).toBe(false)
})

test('every surface-strand parameter drives the rendered 3D', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = trackConsoleErrors(page)
  await openSurfaceStrandsCard(page, '__e2e__surfstrands')
  await page.fill('#oxdna-surfstrand-density', '1000')
  await settle(page)

  // 1000/µm² over a 100 nm circle ≈ 8 strands × 10 nt, rendered as beads AND slabs.
  const base = await caps(page)
  expect(base.capBeads).toBe(80)
  expect(base.capSlabs).toBe(80)
  expect(base.extraNucs).toBe(base.capBeads)

  // Density scales the count.
  await page.fill('#oxdna-surfstrand-density', '3000')
  await settle(page)
  expect((await caps(page)).capBeads).toBe(240)

  // Coverage size scales the area, hence the count.
  await page.fill('#oxdna-surfstrand-size', '200')
  await settle(page)
  const bigger = await caps(page)
  expect(bigger.capBeads).toBeGreaterThan(240)

  // Shape changes the patch and re-scatters.
  await page.selectOption('#oxdna-surfstrand-shape', 'square')
  await settle(page)
  expect(await page.locator('#oxdna-surfstrand-size-label').textContent()).toBe('Width')
  const square = await caps(page)
  expect(square.capBeads).toBeGreaterThan(bigger.capBeads)   // side² > π(d/2)²

  // Sequence length is strand length: 10 nt → 4 nt is 0.4× the beads, same strands.
  await page.fill('#oxdna-surfstrand-seq', 'GCTA')
  await settle(page)
  expect((await caps(page)).capBeads).toBe(square.capBeads * 0.4)

  // A new seed re-scatters the dispersion without changing the count. (That the
  // scatter itself differs per seed is pinned in surface_strands_math.test.js.)
  const seedBefore = await page.inputValue('#oxdna-surfstrand-seed')
  await page.click('#oxdna-surfstrand-seed-new')
  await settle(page)
  expect(await page.inputValue('#oxdna-surfstrand-seed')).not.toBe(seedBefore)
  expect((await caps(page)).capBeads).toBe(square.capBeads * 0.4)

  // Offset moves the coverage patch in the surface plane.
  const patchBefore = (await overlay(page)).patchPos
  await page.fill('#oxdna-surfstrand-offx', '25')
  await settle(page)
  expect((await overlay(page)).patchPos).not.toEqual(patchBefore)

  // Colour reaches the rendered beads (the emitter must not dedupe a colour change).
  await page.fill('#oxdna-surfstrand-color-hex', '#ff8800')
  await settle(page)
  expect((await caps(page)).capBeadColor).toBe('#ff8800')

  // Highlight toggle removes/restores the emphasis layer.
  await page.uncheck('#oxdna-surfstrand-highlight')
  await settle(page)
  expect((await caps(page)).glowCount).toBe(0)

  // Turning the hard surface off ungates and clears everything.
  await page.uncheck('#oxdna-floor-enable')
  await settle(page)
  expect(await page.locator('#oxdna-surfstrand-enable').isChecked()).toBe(false)
  expect((await caps(page)).capBeads).toBe(0)

  // The mrDNA job listing 500s on a stale shared-workspace job dir; unrelated to this card.
  const ours = errors.filter(e => !/500 \(Internal Server Error\)/.test(e))
  expect(ours, ours.join('\n')).toEqual([])
})

test('surface-strand gizmo is removed when entering an assembly', async ({ page }) => {
  test.setTimeout(60_000)
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=__e2e__surfstrands_assembly_gate')
  await page.waitForSelector('#canvas')
  // Reproduce the leaked state directly: an active design-only placement
  // preview exists when assembly mode begins. The setup card itself is already
  // exercised above; this test isolates the assembly visibility boundary.
  await page.evaluate(() => {
    window.__nadocSurfStrands.setShapePreview(true)
    window.__nadocSurfStrands.update({
      enabled: true, sequence: 'GCTA', attachEnd: "5'", shape: 'circle',
      sizeNm: 100, densityPerUm2: 1000, offsetXNm: 0, offsetYNm: 0,
      seed: 1, subjectToField: true,
    }, true)
  })
  expect((await overlay(page)).gizmoVisible).toBe(true)

  const doc = '__e2e__surfstrands_assembly_gate'
  const response = await page.request.post(`${API}/assembly`, {
    data: { name: '__e2e__SurfaceStrandsAssembly' },
    headers: { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc },
  })
  expect(response.ok()).toBe(true)
  await page.evaluate(() => window.__nadocTest.enterAssemblyMode())
  await expect(page.locator('#mode-indicator')).toContainText('ASSEMBLY', { timeout: 10_000 })
  await expect.poll(async () => (await overlay(page)).gizmoVisible).toBe(false)
  const hidden = await overlay(page)
  expect(hidden.visible).toBe(false)
  expect(hidden.gizmoAttached).toBe(false)
  expect(hidden.gizmoEnabled).toBe(false)
  expect(errors).toEqual([])
})

test('an active visualization survives a surface-strand edit', async ({ page }) => {
  test.setTimeout(120_000)
  const headers = await openSurfaceStrandsCard(page, '__e2e__surfviz')
  await page.fill('#oxdna-surfstrand-density', '1000')
  await settle(page)

  // Stand in for a displayed simulation frame + flexibility map + halos, driven
  // through the REAL owners (the anchors card event, the canonical selection).
  const applied = await page.evaluate(() => {
    const dr = window.__nadocDR
    const updates = [], colorByKey = {}
    let strandId = null
    for (const e of dr.getBackboneEntries()) {
      const n = e.nuc
      if (!n || String(n.strand_id).startsWith('cap')) continue
      strandId ??= n.strand_id
      updates.push({
        helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction,
        backbone_position: [n.backbone_position[0], n.backbone_position[1] + 5, n.backbone_position[2]],
      })
      colorByKey[`${n.helix_id}:${n.bp_index}:${n.direction}:0`] = 0xff00ff
    }
    dr.applyFemPositions(updates, 1.0)
    dr.applyScalarColors(colorByKey)
    window.dispatchEvent(new CustomEvent('nadoc:anchors-change', {
      detail: { engine: 'oxdna', highlighted: [{ kind: 'strand', strandId }] },
    }))
    window.__nadocTest.store.setState({ selection: {
      context: 'design', level: 'strand', items: [{ kind: 'strand', id: strandId }],
      primary: { kind: 'strand', id: strandId },
    } })
    return updates.length
  })
  expect(applied).toBeGreaterThan(0)

  const viz = () => page.evaluate(() => {
    const dr = window.__nadocDR
    let sum = 0, n = 0
    for (const e of dr.getBackboneEntries()) {
      if (String(e.nuc?.strand_id).startsWith('cap')) continue
      sum += e.pos.y; n++
    }
    let selGlow = 0
    window.__nadocTest.scene.traverse(o => {
      if (o.isInstancedMesh && o.name === 'selectionGlow') selGlow = o.count
    })
    return {
      meanY: +(sum / n).toFixed(3),
      scalarColored: dr.debugRenderedAudit(999).colors.changed_from_default,
      anchorGlow: dr.anchorGlowCount(),
      selGlow,
      caps: dr.debugCaptureRender().capBeads,
    }
  })

  const before = await viz()
  expect(before.scalarColored).toBe(applied)
  expect(before.anchorGlow).toBeGreaterThan(0)
  expect(before.selGlow).toBeGreaterThan(0)

  // Each of these is a full renderer rebuild. None may disturb the visualization.
  for (const [field, value] of [
    ['#oxdna-surfstrand-density', '3000'],
    ['#oxdna-surfstrand-offx', '10'],
    ['#oxdna-surfstrand-size', '150'],
  ]) {
    await page.fill(field, value)
    await settle(page)
    const now = await viz()
    expect(now.meanY, `${field}=${value} reverted the simulation frame`).toBe(before.meanY)
    expect(now.scalarColored, `${field}=${value} dropped the flexibility map`).toBe(before.scalarColored)
    expect(now.anchorGlow, `${field}=${value} dropped the anchor halo`).toBe(before.anchorGlow)
    expect(now.selGlow, `${field}=${value} dropped the selection halo`).toBe(before.selGlow)
  }
  expect((await viz()).caps).not.toBe(before.caps)   // the edits did take effect

  // A REAL design edit still drops the overlay, and a later strand edit must not
  // resurrect the frame the user dismissed.
  await page.request.post(`${API}/design/helix-at-cell`,
    { data: { row: 2, col: 2, length_bp: 120 }, headers })
  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: d })
    bc.close()
  }, '__e2e__surfviz')
  await expect.poll(async () => (await viz()).meanY, { timeout: 15_000 }).not.toBe(before.meanY)
  const dismissed = (await viz()).meanY
  await page.fill('#oxdna-surfstrand-density', '2000')
  await settle(page)
  expect((await viz()).meanY, 'a dismissed simulation frame came back').toBe(dismissed)
})
