/**
 * Playwright troubleshooting: the mrDNA "deform display" toggle collapsed one
 * helix of a tight bundle (2hb_2xT) into a bead RING (reported artifact).
 *
 * Root cause was backend: for a FINE multiresolution job the display
 * reconstruction assigned beads to the nearest DESIGN axis, and on a 2hb the two
 * helices are ~2.3 nm apart so one helix's drifted beads got dumped onto its
 * neighbour → its spline collapsed. Fixed by falling back to the coarse stage when
 * a helix collapses (mrdna_runner._override_has_collapsed_helix).
 *
 * This spec loads the design, applies the REAL /display payload through the real
 * design_renderer path, and asserts every helix spans a healthy extent (no ring) +
 * captures a screenshot.
 */

import { test, expect } from '@playwright/test'

const JOB_ID = '69157b516895'   // completed 200k-fine job for 2hb_2xT

test('mrDNA deform display does not collapse a tight-bundle helix into a ring', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('#library-panel-mount')).toBeVisible()

  const item = page.locator('#library-panel-mount').getByText('2hb_2xT', { exact: false }).first()
  if (!(await item.count())) test.skip(true, 'workspace design 2hb_2xT not present')
  await item.click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 15_000 })
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.designRenderer)
  await page.waitForTimeout(1200)

  // Fetch the live display payload and apply it through the real renderer path
  // (same call mrdna_display.showDeform makes).
  const perHelix = await page.evaluate(async (jobId) => {
    const res = await fetch(`/api/mrdna/jobs/${jobId}/display`)
    if (!res.ok) return { error: `display ${res.status}` }
    const data = await res.json()
    const positions = Array.isArray(data) ? data : data.positions
    window.__NADOC_DBG__.designRenderer.applyFemPositions(positions)

    // Group real-nucleotide backbone positions by helix and measure the 3-D
    // bounding-box diagonal — a collapsed helix is a small blob (< ~4 nm),
    // a healthy 42-bp helix spans ~14 nm.
    const by = {}
    for (const p of positions) {
      if (p.helix_id === '__xb__') continue
      ;(by[p.helix_id] ||= []).push(p.backbone_position)
    }
    const out = {}
    for (const [h, ps] of Object.entries(by)) {
      const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity]
      for (const q of ps) for (let i = 0; i < 3; i++) { mn[i] = Math.min(mn[i], q[i]); mx[i] = Math.max(mx[i], q[i]) }
      out[h] = Math.hypot(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2])
    }
    return out
  }, JOB_ID)

  await page.waitForTimeout(600)
  await page.screenshot({ path: 'e2e/bench_results/mrdna_2hb_display_fixed.png' })

  expect(perHelix.error, `display fetch failed: ${perHelix.error}`).toBeFalsy()
  const extents = Object.entries(perHelix)
  expect(extents.length, 'both helices present').toBeGreaterThanOrEqual(2)
  // No helix collapsed into a ring: each spans well over half its ~14 nm contour.
  for (const [h, ext] of extents) {
    expect(ext, `helix ${h} collapsed to ${ext.toFixed(1)} nm (ring artifact)`).toBeGreaterThan(6.0)
  }
})
