/**
 * Playwright test: skip insert + delete restores design state.
 *
 * Creates a 6HB HC bundle, runs auto-crossover + autobreak, snapshots the
 * design state, inserts a skip on one helix, then deletes that skip (delta=0)
 * and verifies the design matches the pre-skip snapshot exactly:
 *   - Same number of crossovers with identical half_a/half_b positions
 *   - Same number of strands with identical domain boundaries
 *   - No loop_skips remaining on any helix
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000/api'
const CELLS_6HB = [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]
const LENGTH_BP = 126

/**
 * Produce a canonical fingerprint of the design's topology:
 *   - sorted crossover descriptors (helix+bp+strand for both halves)
 *   - sorted strand domain descriptors (helix+bp range+direction)
 *   - sorted loop_skip entries across all helices
 */
function designFingerprint(design) {
  // Crossovers — sort by a stable key
  const xovers = (design.crossovers ?? []).map(xo => {
    const a = `${xo.half_a.helix_id}|${xo.half_a.index}|${xo.half_a.strand}`
    const b = `${xo.half_b.helix_id}|${xo.half_b.index}|${xo.half_b.strand}`
    return a < b ? `${a}::${b}` : `${b}::${a}`
  }).sort()

  // Strand domains — for each strand, record domain chain
  const strands = design.strands.map(s => {
    const doms = s.domains.map(d => {
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      return `${d.helix_id}|${lo}-${hi}|${d.direction}`
    }).join(' → ')
    return `${s.strand_type}:${doms}`
  }).sort()

  // Loop/skips across all helices
  const loopSkips = design.helices.flatMap(h =>
    (h.loop_skips ?? []).map(ls => `${h.id}|${ls.bp_index}|${ls.delta}`)
  ).sort()

  return { xovers, strands, loopSkips }
}

test.describe('Skip delete restores design', () => {

  test('6HB: autocrossover + autobreak → add skip → delete skip → same state', async ({ page }) => {
    // ── 1. Create bundle ────────────────────────────────────────────────────
    const bundleRes = await page.request.post(`${API}/design/bundle`, {
      data: { cells: CELLS_6HB, length_bp: LENGTH_BP, name: 'skip_restore_test', plane: 'XY' },
    })
    expect(bundleRes.ok()).toBeTruthy()

    // ── 2. Auto-crossover ───────────────────────────────────────────────────
    const xoverRes = await page.request.post(`${API}/design/crossovers/auto`)
    expect(xoverRes.ok()).toBeTruthy()
    const designXover = (await xoverRes.json()).design
    expect(designXover.crossovers.length).toBeGreaterThan(0)
    console.log(`Crossovers placed: ${designXover.crossovers.length}`)

    // ── 3. Auto-break ───────────────────────────────────────────────────────
    const breakRes = await page.request.post(`${API}/design/auto-break`)
    expect(breakRes.ok()).toBeTruthy()
    const designBroken = (await breakRes.json()).design
    console.log(`Strands after autobreak: ${designBroken.strands.length}`)
    console.log(`Crossovers after autobreak: ${designBroken.crossovers.length}`)

    // ── 4. Snapshot the "before skip" state ─────────────────────────────────
    const fpBefore = designFingerprint(designBroken)
    expect(fpBefore.loopSkips.length).toBe(0)

    // Pick a helix and a bp in the middle for the skip
    const helix = designBroken.helices[0]
    const skipBp = helix.bp_start + Math.floor(helix.length_bp / 2)
    console.log(`Inserting skip on helix ${helix.id.slice(0, 12)} at bp ${skipBp}`)

    // ── 5. Insert skip (delta=-1) ───────────────────────────────────────────
    const insertRes = await page.request.post(`${API}/design/loop-skip/insert`, {
      data: { helix_id: helix.id, bp_index: skipBp, delta: -1 },
    })
    expect(insertRes.ok()).toBeTruthy()
    const designWithSkip = (await insertRes.json()).design

    // Verify the skip was actually placed
    const skipHelix = designWithSkip.helices.find(h => h.id === helix.id)
    const skipEntry = skipHelix.loop_skips.find(ls => ls.bp_index === skipBp && ls.delta === -1)
    expect(skipEntry).toBeTruthy()
    console.log(`Skip placed. loop_skips on helix: ${skipHelix.loop_skips.length}`)

    const fpWithSkip = designFingerprint(designWithSkip)
    console.log(`Crossovers with skip: ${fpWithSkip.xovers.length}`)
    console.log(`Strands with skip: ${fpWithSkip.strands.length}`)

    // ── 6. Delete the skip (delta=0) ────────────────────────────────────────
    const deleteRes = await page.request.post(`${API}/design/loop-skip/insert`, {
      data: { helix_id: helix.id, bp_index: skipBp, delta: 0 },
    })
    expect(deleteRes.ok()).toBeTruthy()
    const designAfterDelete = (await deleteRes.json()).design

    // Verify skip is gone
    const afterHelix = designAfterDelete.helices.find(h => h.id === helix.id)
    const remainingSkips = afterHelix.loop_skips.filter(ls => ls.bp_index === skipBp)
    expect(remainingSkips.length).toBe(0)

    // ── 7. Compare: design must match pre-skip state ────────────────────────
    const fpAfter = designFingerprint(designAfterDelete)

    // No loop/skips should remain
    expect(fpAfter.loopSkips).toEqual([])

    // Crossovers must be identical
    expect(fpAfter.xovers.length).toBe(fpBefore.xovers.length)
    expect(fpAfter.xovers).toEqual(fpBefore.xovers)

    // Strands (domain topology) must be identical
    expect(fpAfter.strands.length).toBe(fpBefore.strands.length)
    expect(fpAfter.strands).toEqual(fpBefore.strands)

    console.log('Design restored successfully — crossovers, strands, and loop_skips all match.')
  })

  test('6HB: skip on multiple helices → delete all → restored', async ({ page }) => {
    // ── 1. Create bundle ────────────────────────────────────────────────────
    const bundleRes = await page.request.post(`${API}/design/bundle`, {
      data: { cells: CELLS_6HB, length_bp: LENGTH_BP, name: 'multi_skip_test', plane: 'XY' },
    })
    expect(bundleRes.ok()).toBeTruthy()

    // ── 2. Auto-crossover + autobreak ───────────────────────────────────────
    const xoverRes = await page.request.post(`${API}/design/crossovers/auto`)
    expect(xoverRes.ok()).toBeTruthy()
    const breakRes = await page.request.post(`${API}/design/auto-break`)
    expect(breakRes.ok()).toBeTruthy()
    const designBroken = (await breakRes.json()).design

    const fpBefore = designFingerprint(designBroken)

    // ── 3. Insert skips on first 3 helices ──────────────────────────────────
    const targets = designBroken.helices.slice(0, 3).map(h => ({
      helix_id: h.id,
      bp_index: h.bp_start + Math.floor(h.length_bp / 2),
    }))

    for (const t of targets) {
      const r = await page.request.post(`${API}/design/loop-skip/insert`, {
        data: { helix_id: t.helix_id, bp_index: t.bp_index, delta: -1 },
      })
      expect(r.ok()).toBeTruthy()
    }

    // Verify all 3 skips present
    const midDesign = (await (await page.request.get(`${API}/design`)).json()).design
    let totalSkips = midDesign.helices.reduce((n, h) => n + (h.loop_skips?.length ?? 0), 0)
    expect(totalSkips).toBe(3)

    // ── 4. Delete all skips ─────────────────────────────────────────────────
    for (const t of targets) {
      const r = await page.request.post(`${API}/design/loop-skip/insert`, {
        data: { helix_id: t.helix_id, bp_index: t.bp_index, delta: 0 },
      })
      expect(r.ok()).toBeTruthy()
    }

    // ── 5. Verify restored ──────────────────────────────────────────────────
    const finalDesign = (await (await page.request.get(`${API}/design`)).json()).design
    const fpAfter = designFingerprint(finalDesign)

    expect(fpAfter.loopSkips).toEqual([])
    expect(fpAfter.xovers).toEqual(fpBefore.xovers)
    expect(fpAfter.strands).toEqual(fpBefore.strands)

    console.log('Multi-skip restore verified — all 3 skips removed, design matches.')
  })
})
