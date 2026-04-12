/**
 * Playwright test: autobreak on crossover-circular strands.
 *
 * Loads Examples/hingeV4.nadoc which contains a 64-nt circular staple strand
 * on helices h_XY_0_0 (REVERSE) and h_XY_0_1 (FORWARD) between bp 96-127,
 * connected by crossovers at bp 96 and bp 127.
 *
 * After autobreak, verifies:
 *   - Full staple coverage in the bp 86-127 range on both helices
 *   - All crossovers between h_XY_0_0 and h_XY_0_1 are evidenced in strands
 *   - No staple strand exceeds 60 nt
 *   - The formerly-circular strand is properly nicked and re-ligated
 */

import { test, expect } from '@playwright/test'
import * as path from 'path'

const API = 'http://localhost:8000/api'
const H0 = 'h_XY_0_0'
const H1 = 'h_XY_0_1'
const BP_LO = 86
const BP_HI = 127

/** Collect staple coverage as a Set of "helix|bp|direction" keys. */
function coverage(design, bpLo, bpHi, helixIds) {
  const cov = new Set()
  for (const s of design.strands) {
    if (s.strand_type === 'scaffold') continue
    for (const d of s.domains) {
      if (helixIds && !helixIds.has(d.helix_id)) continue
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      for (let bp = Math.max(lo, bpLo); bp <= Math.min(hi, bpHi); bp++) {
        cov.add(`${d.helix_id}|${bp}|${d.direction}`)
      }
    }
  }
  return cov
}

/**
 * Check that a crossover is *ligated* in the strand graph — i.e. both
 * sides are consecutive domains within a single strand.
 *
 * Two valid forms:
 *   a) Inter-domain boundary within one strand (consecutive domains).
 *   b) 3'->5' wrap-around within one strand (last->first domain).
 *
 * A cross-strand nick (two separate strands whose terminals coincide
 * with the crossover positions) is NOT considered ligated — it will
 * render as a visual disconnect in the cadnano pathview.
 */
function isCrossoverLigated(xo, design) {
  const ha = xo.half_a, hb = xo.half_b

  for (const strand of design.strands) {
    // (a) Inter-domain boundary
    for (let di = 0; di < strand.domains.length - 1; di++) {
      const d0 = strand.domains[di], d1 = strand.domains[di + 1]
      if (d0.helix_id === ha.helix_id && d0.end_bp === ha.index &&
          d1.helix_id === hb.helix_id && d1.start_bp === hb.index) return true
      if (d0.helix_id === hb.helix_id && d0.end_bp === hb.index &&
          d1.helix_id === ha.helix_id && d1.start_bp === ha.index) return true
    }
    // (b) Wrap-around
    if (strand.domains.length >= 2) {
      const last = strand.domains[strand.domains.length - 1]
      const first = strand.domains[0]
      if (last.helix_id === ha.helix_id && last.end_bp === ha.index &&
          first.helix_id === hb.helix_id && first.start_bp === hb.index) return true
      if (last.helix_id === hb.helix_id && last.end_bp === hb.index &&
          first.helix_id === ha.helix_id && first.start_bp === ha.index) return true
    }
  }

  return false
}

test.describe('Autobreak circular strand (hingeV4)', () => {

  test('crossovers between h0/h1 bp 86-127 stay connected after autobreak', async ({ page }) => {
    // ── 1. Load hingeV4.nadoc ──────────────────────────────────────────────
    const nadocPath = path.resolve(
      import.meta.dirname ?? __dirname,
      '../../Examples/hingeV4.nadoc',
    )
    const loadRes = await page.request.post(`${API}/design/load`, {
      data: { path: nadocPath },
    })
    expect(loadRes.ok()).toBeTruthy()
    const designBefore = (await loadRes.json()).design

    // Sanity: confirm the 64-nt circular strand exists before autobreak
    const helixIds = new Set([H0, H1])
    const circularStrand = designBefore.strands.find(s => {
      if (s.strand_type === 'scaffold') return false
      if (s.domains.length !== 2) return false
      const [d0, d1] = s.domains
      const d0h = d0.helix_id, d1h = d1.helix_id
      if (!helixIds.has(d0h) || !helixIds.has(d1h)) return false
      const lo0 = Math.min(d0.start_bp, d0.end_bp)
      const hi0 = Math.max(d0.start_bp, d0.end_bp)
      const lo1 = Math.min(d1.start_bp, d1.end_bp)
      const hi1 = Math.max(d1.start_bp, d1.end_bp)
      return lo0 === 96 && hi0 === 127 && lo1 === 96 && hi1 === 127
    })
    expect(circularStrand, 'Expected 64-nt circular strand on h0/h1 bp 96-127').toBeTruthy()
    const circNt = circularStrand.domains.reduce(
      (sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0,
    )
    expect(circNt).toBe(64)

    // Identify crossovers between h0 and h1 in the bp range
    const relevantXovers = designBefore.crossovers.filter(xo => {
      const ha = xo.half_a, hb = xo.half_b
      if (!helixIds.has(ha.helix_id) || !helixIds.has(hb.helix_id)) return false
      return ha.index >= BP_LO && ha.index <= BP_HI
    })
    console.log(`Relevant crossovers (h0<->h1, bp ${BP_LO}-${BP_HI}): ${relevantXovers.length}`)
    expect(relevantXovers.length).toBeGreaterThan(0)

    // ── 2. Run autobreak ───────────────────────────────────────────────────
    const breakRes = await page.request.post(`${API}/design/auto-break`)
    expect(breakRes.ok()).toBeTruthy()
    const designAfter = (await breakRes.json()).design

    // ── 3. Verify: all staples <= 60 nt ────────────────────────────────────
    for (const s of designAfter.strands) {
      if (s.strand_type === 'scaffold') continue
      const nt = s.domains.reduce(
        (sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0,
      )
      expect(nt, `Strand ${s.id} has ${nt} nt (max 60)`).toBeLessThanOrEqual(60)
    }

    // ── 4. Verify: full staple coverage in bp 86-127 on h0 (REV) and h1 (FWD)
    const cov = coverage(designAfter, BP_LO, BP_HI, helixIds)
    for (let bp = BP_LO; bp <= BP_HI; bp++) {
      // h_XY_0_0 row=0,col=0 even parity -> staple REVERSE
      expect(cov.has(`${H0}|${bp}|REVERSE`),
        `Missing staple coverage: ${H0} bp=${bp} REVERSE`).toBeTruthy()
      // h_XY_0_1 row=0,col=1 odd parity -> staple FORWARD
      expect(cov.has(`${H1}|${bp}|FORWARD`),
        `Missing staple coverage: ${H1} bp=${bp} FORWARD`).toBeTruthy()
    }

    // ── 5. Verify: crossover count unchanged after autobreak ───────────────
    const xoBefore = designBefore.crossovers.length
    const xoAfter = designAfter.crossovers.length
    expect(xoAfter, 'Crossover count changed after autobreak').toBe(xoBefore)

    // ── 6. Verify: all crossovers between h0/h1 in range are LIGATED ─────
    // A cross-strand nick is not enough — the crossover must be an
    // inter-domain boundary within a single strand so that the pathview
    // renders it as connected.
    for (const xo of relevantXovers) {
      const ha = xo.half_a, hb = xo.half_b
      const ok = isCrossoverLigated(xo, designAfter)
      expect(ok,
        `Crossover at bp=${ha.index} (${ha.helix_id} ${ha.strand} <-> ${hb.helix_id} ${hb.strand}) ` +
        `is NOT ligated after autobreak — would render as disconnect`,
      ).toBeTruthy()
    }

    // ── 7. Verify: the old 64-nt circular strand was split correctly ───────
    // After autobreak, there should be NO single 64-nt strand in this region
    const bigStrands = designAfter.strands.filter(s => {
      if (s.strand_type === 'scaffold') return false
      const nt = s.domains.reduce(
        (sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0,
      )
      if (nt < 60) return false
      return s.domains.some(d =>
        helixIds.has(d.helix_id) &&
        Math.min(d.start_bp, d.end_bp) >= 96 &&
        Math.max(d.start_bp, d.end_bp) <= 127,
      )
    })
    expect(bigStrands.length,
      'Expected the 64-nt circular strand to be split into smaller strands',
    ).toBe(0)

    // ── 8. Log the resulting strands in the region for debugging ───────────
    const regionStrands = designAfter.strands.filter(s => {
      if (s.strand_type === 'scaffold') return false
      return s.domains.some(d => {
        if (!helixIds.has(d.helix_id)) return false
        const lo = Math.min(d.start_bp, d.end_bp)
        const hi = Math.max(d.start_bp, d.end_bp)
        return lo <= BP_HI && hi >= BP_LO
      })
    })
    for (const s of regionStrands) {
      const nt = s.domains.reduce(
        (sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0,
      )
      const domStr = s.domains.map(d =>
        `${d.helix_id.slice(-3)} ${d.start_bp}->${d.end_bp} ${d.direction}`,
      ).join(' | ')
      console.log(`  strand ${s.id.slice(0, 25)} (${nt} nt): ${domStr}`)
    }
  })
})
