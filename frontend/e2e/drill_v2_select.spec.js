/**
 * ISSUE-4 Phase 2 — drill-v2 (unified selectionLevel) gesture validation.
 *
 * Boots the app with the NADOC_DRILL_V2 flag on (?drillv2=1) and exercises the
 * default-level click ladder through the REAL raycast on a real scaffolded part:
 *
 *   1st click on a bead          → STRAND          (decision B: strand-first)
 *   2nd click on the same bead   → that nucleotide (the leaf under the cursor)
 *   3rd click on the same bead   → STAYS the nucleotide (repeat click keeps the
 *                                  leaf selected — no toggle-clear, user feedback 2026-06-06)
 *
 * This is the discriminator vs legacy auto-drill (which would give cluster→strand
 * →domain→bead). Same robust pattern as bead_select.spec.js: pick a real bead via
 * pickBeadAt, click it, assert on exposed state, retry candidates on a miss.
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, beadCandidates } from './helpers/scene_harness.js'

test.describe('Drill v2 — default-level click ladder', () => {
  test('1st click → strand, 2nd → nucleotide, 3rd → keeps the nucleotide', async ({ page }) => {
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

    // 3rd click on the same leaf → KEEPS the nucleotide selected (no toggle-clear).
    await page.mouse.click(landed.x, landed.y)
    await page.waitForTimeout(120)
    const sel3 = await page.evaluate(() => window.__nadocTest.getSelectedObject())
    expect(sel3?.type, '3rd click on the same leaf keeps the nucleotide selected').toBe('nucleotide')
  })

  // An engaged level must PERSIST across an empty-space (deselect) click — the
  // filter button stays lit until Tab cycles away or it is re-clicked (user
  // feedback 2026-06-06). Before the fix, _clearAll emitted null → the button
  // un-highlighted on every empty click.
  test('an engaged level survives an empty-space click (button stays lit)', async ({ page }) => {
    await loadScaffoldedPart(page, { doc: 'e2e-drillv2lvl', name: 'drillv2lvl', extraQuery: '&drillv2=1' })

    // Engage the cluster level via its filter button.
    const clustBtn = '#select-filter .sf-btn[data-key="clust"]'
    await page.click(clustBtn)
    expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel()), 'cluster engaged').toBe('cluster')
    expect(await page.locator(clustBtn).evaluate(b => b.classList.contains('active')), 'button lit').toBe(true)

    // Click a genuinely empty canvas point (raycast hits nothing, not under a panel).
    const box = await page.locator('#canvas').boundingBox()
    const rects = []
    for (const sel of ['#menu-bar', '#left-panel', '#right-panel']) {
      const b = await page.locator(sel).boundingBox().catch(() => null)
      if (b) rects.push(b)
    }
    const empty = await page.evaluate(({ box, rects }) => {
      const covered = (x, y) => rects.some(r => x >= r.x && x <= r.x + r.width && y >= r.y && y <= r.y + r.height)
      for (let fy = 0.15; fy <= 0.85; fy += 0.08) {
        for (let fx = 0.12; fx <= 0.88; fx += 0.08) {
          const x = box.x + box.width * fx, y = box.y + box.height * fy
          if (covered(x, y)) continue
          if (window.__nadocTest.pickBeadAt(x, y)) continue
          return { x, y }
        }
      }
      return null
    }, { box, rects })
    expect(empty, 'found an empty canvas point').not.toBeNull()
    await page.mouse.click(empty.x, empty.y)
    await page.waitForTimeout(120)

    // The level + button highlight must persist (the fix).
    expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel()), 'level persists after empty click').toBe('cluster')
    expect(await page.locator(clustBtn).evaluate(b => b.classList.contains('active')), 'button stays lit').toBe(true)
  })

  // ISSUE-4 Phase 3 — the would-be-selected leaf gets a RED PREVIEW GLOW on hover.
  // Discriminator vs the Phase-2 scale-pop: the named 'previewGlow' layer is empty
  // (count 0) under the old behaviour and non-empty once a candidate is hovered.
  test('hover over a selected strand pops the red preview glow', async ({ page }) => {
    await loadScaffoldedPart(page, { doc: 'e2e-drillv2hov', name: 'drillv2hov', extraQuery: '&drillv2=1' })

    const previewCount = () => page.evaluate(() => {
      let n = 0
      window.__nadocTest.scene.traverse(o => { if (o.isInstancedMesh && o.name === 'previewGlow') n = o.count })
      return n
    })

    // Before any selection the preview layer is empty.
    expect(await previewCount(), 'no preview glow before a strand is selected').toBe(0)

    // 1st click on a real bead → STRAND (default level), then hover that same bead.
    const cands = await beadCandidates(page)
    let landed = null
    for (const p of cands) {
      const hit = await page.evaluate(pt => window.__nadocTest.pickBeadAt(pt.x, pt.y), p)
      if (!hit) continue
      await page.mouse.click(p.x, p.y)
      await page.waitForTimeout(120)
      const sel = await page.evaluate(() => window.__nadocTest.getSelectedObject())
      if (sel?.type === 'strand') { landed = p; break }
    }
    expect(landed, 'a 1st click resolved to a STRAND').not.toBeNull()

    // Move off, then onto the selected strand's bead → the red preview glow appears.
    await page.mouse.move(landed.x + 60, landed.y + 60)
    await page.waitForTimeout(60)
    await page.mouse.move(landed.x, landed.y)
    await page.waitForTimeout(120)
    expect(await previewCount(), 'hovering the selected strand pops the red preview glow').toBeGreaterThan(0)
  })
})
