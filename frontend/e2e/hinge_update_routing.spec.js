/**
 * Playwright test: verify Update Routing places loop/skips only at bp positions
 * covered by strand domains on Hinge.nadoc (a square-lattice design with
 * helices that have non-zero bp_start values).
 *
 * Regression for the sq_lattice_periodic_skips LOCAL/GLOBAL coordinate bug:
 * the function was generating bp_index values in LOCAL space (0..length_bp-1)
 * but the rest of the system uses GLOBAL coordinates (bp_start..bp_start+length_bp-1).
 * For helices with bp_start != 0 this placed skip marks in blank space before
 * the helix's DNA begins.
 */

import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'

const API    = 'http://localhost:8000/api'
const DESIGN = '/home/joshua/NADOC/workspace/Hinge.nadoc'

async function loadHinge(page) {
  const content = readFileSync(DESIGN, 'utf-8')
  const resp = await page.request.post(`${API}/design/import`, { data: { content } })
  expect(resp.ok(), 'import Hinge.nadoc').toBeTruthy()
}

/** Build per-helix merged coverage intervals [[lo, hi], ...] from strand domains. */
function buildCoverage(design) {
  const raw = new Map()
  for (const strand of design.strands ?? []) {
    for (const dom of strand.domains ?? []) {
      const lo = Math.min(dom.start_bp, dom.end_bp)
      const hi = Math.max(dom.start_bp, dom.end_bp)
      if (!raw.has(dom.helix_id)) raw.set(dom.helix_id, [])
      raw.get(dom.helix_id).push([lo, hi])
    }
  }
  const merged = new Map()
  for (const [hid, ivls] of raw) {
    ivls.sort((a, b) => a[0] - b[0])
    const m = [ivls[0].slice()]
    for (const [lo, hi] of ivls.slice(1)) {
      const last = m[m.length - 1]
      if (lo <= last[1] + 1) last[1] = Math.max(last[1], hi)
      else m.push([lo, hi])
    }
    merged.set(hid, m)
  }
  return merged
}

function isCovered(intervals, bp) {
  for (const [lo, hi] of intervals) {
    if (bp < lo) return false
    if (bp <= hi) return true
  }
  return false
}

test.describe('Hinge.nadoc — Update Routing skip placement', () => {
  test.setTimeout(60_000)

  test('apply-deformations places no skips outside domain coverage', async ({ page }) => {
    await loadHinge(page)

    // Clear any stale skips present in the file.
    const clearRes = await page.request.post(`${API}/design/loop-skip/clear-all`)
    expect(clearRes.ok(), 'clear-all').toBeTruthy()

    // Run Update Routing (equivalent to key [4] in the editor).
    const routeRes = await page.request.post(`${API}/design/loop-skip/apply-deformations`)
    if (!routeRes.ok()) {
      const body = await routeRes.json().catch(() => ({}))
      console.error('apply-deformations failed:', routeRes.status(), JSON.stringify(body))
    }
    expect(routeRes.ok(), 'apply-deformations').toBeTruthy()

    const design = (await routeRes.json()).design

    const coverage = buildCoverage(design)

    // Collect every helix / bp_index pair that falls outside domain coverage.
    const orphans = []
    for (const h of design.helices ?? []) {
      const ivls = coverage.get(h.id) ?? []
      for (const ls of h.loop_skips ?? []) {
        if (!isCovered(ivls, ls.bp_index)) {
          orphans.push({
            helix_id:  h.id,
            bp_start:  h.bp_start,
            length_bp: h.length_bp,
            bp_index:  ls.bp_index,
            delta:     ls.delta,
            domain:    ivls,
          })
        }
      }
    }

    if (orphans.length) {
      console.log(`\n${orphans.length} orphaned skip(s) outside domain coverage:`)
      for (const v of orphans) {
        console.log(
          `  ${v.helix_id}  bp_start=${v.bp_start}  bp_index=${v.bp_index}  ` +
          `domain=${JSON.stringify(v.domain)}`
        )
      }
    }

    expect(orphans).toEqual([])
  })

  test('no skip lands in a single-stranded-only region (fwd ∩ rev = dsDNA)', async ({ page }) => {
    await loadHinge(page)

    const clearRes = await page.request.post(`${API}/design/loop-skip/clear-all`)
    expect(clearRes.ok(), 'clear-all').toBeTruthy()

    const routeRes = await page.request.post(`${API}/design/loop-skip/apply-deformations`)
    expect(routeRes.ok(), 'apply-deformations').toBeTruthy()
    const design = (await routeRes.json()).design

    // dsDNA intervals per helix = FORWARD intervals ∩ REVERSE intervals.
    function dsDNAIntervals(design, helixId) {
      const fwd = [], rev = []
      for (const strand of design.strands ?? []) {
        for (const dom of strand.domains ?? []) {
          if (dom.helix_id !== helixId) continue
          const lo = Math.min(dom.start_bp, dom.end_bp)
          const hi = Math.max(dom.start_bp, dom.end_bp) + 1  // exclusive
          if (dom.direction === 'FORWARD') fwd.push([lo, hi])
          else rev.push([lo, hi])
        }
      }
      const merge = ivls => {
        if (!ivls.length) return []
        ivls.sort((a, b) => a[0] - b[0])
        const m = [ivls[0].slice()]
        for (const [lo, hi] of ivls.slice(1)) {
          const last = m[m.length - 1]
          if (lo <= last[1]) last[1] = Math.max(last[1], hi)
          else m.push([lo, hi])
        }
        return m
      }
      const intersect = (a, b) => {
        const res = []; let ai = 0, bi = 0
        while (ai < a.length && bi < b.length) {
          const lo = Math.max(a[ai][0], b[bi][0])
          const hi = Math.min(a[ai][1], b[bi][1])
          if (lo < hi) res.push([lo, hi])
          if (a[ai][1] < b[bi][1]) ai++; else bi++
        }
        return res
      }
      return intersect(merge(fwd), merge(rev))
    }

    const ssDNA = []
    for (const h of design.helices ?? []) {
      const ds = dsDNAIntervals(design, h.id)
      for (const ls of h.loop_skips ?? []) {
        const covered = ds.some(([lo, hi]) => ls.bp_index >= lo && ls.bp_index < hi)
        if (!covered) {
          ssDNA.push({ helix_id: h.id, bp_index: ls.bp_index, ds_intervals: ds })
        }
      }
    }

    if (ssDNA.length) {
      console.log(`\nSkips in ssDNA-only regions:`)
      for (const v of ssDNA)
        console.log(`  ${v.helix_id}: bp_index=${v.bp_index} ds=${JSON.stringify(v.ds_intervals)}`)
    }

    expect(ssDNA).toEqual([])
  })

  test('every skip bp_index is within helix [bp_start, bp_start+length_bp)', async ({ page }) => {
    await loadHinge(page)

    const clearRes = await page.request.post(`${API}/design/loop-skip/clear-all`)
    expect(clearRes.ok(), 'clear-all').toBeTruthy()

    const routeRes = await page.request.post(`${API}/design/loop-skip/apply-deformations`)
    expect(routeRes.ok(), 'apply-deformations').toBeTruthy()

    const design = (await routeRes.json()).design

    const outOfRange = []
    for (const h of design.helices ?? []) {
      const lo = h.bp_start
      const hi = h.bp_start + h.length_bp
      for (const ls of h.loop_skips ?? []) {
        if (ls.bp_index < lo || ls.bp_index >= hi) {
          outOfRange.push({
            helix_id:  h.id,
            bp_start:  h.bp_start,
            length_bp: h.length_bp,
            bp_index:  ls.bp_index,
          })
        }
      }
    }

    if (outOfRange.length) {
      console.log(`\nOut-of-range bp_index (LOCAL/GLOBAL coordinate mismatch):`)
      for (const v of outOfRange) {
        const local = v.bp_index - v.bp_start
        console.log(
          `  ${v.helix_id}: bp_index=${v.bp_index} not in [${v.bp_start},${v.bp_start + v.length_bp})` +
          ` — looks like LOCAL index ${local} was stored instead of GLOBAL ${v.bp_index}`
        )
      }
    }

    expect(outOfRange).toEqual([])
  })
})
