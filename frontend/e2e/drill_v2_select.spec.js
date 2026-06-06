/**
 * ISSUE-4 Phase 2 — drill-v2 (unified selectionLevel) gesture validation.
 *
 * Boots the app with the NADOC_DRILL_V2 flag on (?drillv2=1) and exercises the
 * default-level click ladder through the REAL raycast on a real scaffolded part:
 *
 *   1st click on a bead          → STRAND          (decision B: strand-first)
 *   2nd click on the same bead   → that nucleotide (the leaf under the cursor)
 *   3rd click on the same bead   → cleared         (toggle off)
 *
 * This is the discriminator vs legacy auto-drill (which would give cluster→strand
 * →domain→bead). Same robust pattern as bead_select.spec.js: pick a real bead via
 * pickBeadAt, click it, assert on exposed state, retry candidates on a miss.
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, beadCandidates } from './helpers/scene_harness.js'

test.describe('Drill v2 — default-level click ladder', () => {
  test('1st click → strand, 2nd → nucleotide, 3rd → clear', async ({ page }) => {
    await loadScaffoldedPart(page, { doc: 'e2e-drillv2', name: 'drillv2', extraQuery: '&drillv2=1' })

    // Sanity: the flag is actually on for this boot.
    const v2on = await page.evaluate(() => new URLSearchParams(location.search).get('drillv2') === '1')
    expect(v2on, 'booted with drillv2=1').toBe(true)

    // Find a bead the real raycast resolves, then drive the ladder on that point.
    const cands = await beadCandidates(page)
    let landed = null
    for (const p of cands) {
      const hit = await page.evaluate(pt => window.__nadocTest.pickBeadAt(pt.x, pt.y), p)
      if (!hit) continue
      await page.mouse.click(p.x, p.y)
      await page.waitForTimeout(120)
      const sel = await page.evaluate(() => window.__nadocTest.getSelectedObject())
      if (sel?.type === 'strand') { landed = p; break }   // 1st click → STRAND
    }
    expect(landed, 'a 1st click resolved to a STRAND (decision B)').not.toBeNull()

    // 2nd click on the same bead → the nucleotide leaf under the cursor.
    await page.mouse.click(landed.x, landed.y)
    await page.waitForTimeout(120)
    const sel2 = await page.evaluate(() => window.__nadocTest.getSelectedObject())
    expect(sel2?.type, '2nd click → leaf nucleotide').toBe('nucleotide')

    // 3rd click on the same leaf → toggle clear.
    await page.mouse.click(landed.x, landed.y)
    await page.waitForTimeout(120)
    const sel3 = await page.evaluate(() => window.__nadocTest.getSelectedObject())
    expect(sel3, '3rd click on the same leaf clears the selection').toBeNull()
  })
})
