/**
 * Playwright: crossover extra bases render at their REAL simulated positions.
 *
 * Opens the workspace design 6hb_2xT (24 crossovers carrying "TT" extra bases),
 * then pushes an oxDNA-display-shaped frame whose "__xb__" entries place one
 * crossover's inserts far from the geometric Bezier arc.  Asserts those extra-base
 * bead instances move to the simulated positions and revert to the arc when the
 * overlay clears.  Exercises the real design_renderer path
 * (partitionExtraBaseUpdates → applyClusterCrossoverUpdate → setExtraBaseInstanceFromSim).
 */

import { test, expect } from '@playwright/test'

const readBeads = (sids) => {
  const dr = window.__NADOC_DBG__.designRenderer
  return dr.getXoverBeadGlowEntries(sids)
    .map((e) => ({ k: e.localIdx, xoId: e.arcData.xoId, pos: [e.pos.x, e.pos.y, e.pos.z] }))
}

test('extra-base beads follow simulated positions, then revert to the arc', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('#library-panel-mount')).toBeVisible()

  // Open the user's extra-base design from the workspace library (skip if absent —
  // this fixture is a workspace design, not committed to the repo).
  const item = page.locator('#library-panel-mount').getByText('6hb_2xT', { exact: false }).first()
  if (!(await item.count())) test.skip(true, 'workspace design 6hb_2xT not present')
  await item.click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 15_000 })
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.designRenderer)
  await page.waitForTimeout(1500)

  // Source ids from the RENDERED design (its crossover ids are what the beads key on).
  const { xoId, n, strandIds } = await page.evaluate(() => {
    const cd = window.__NADOC_DBG__.store.getState().currentDesign
    const xo = cd.crossovers.find((x) => x.extra_bases)
    return { xoId: xo.id, n: xo.extra_bases.length, strandIds: cd.strands.map((s) => s.id) }
  })
  expect(n).toBeGreaterThan(0)

  // Establish the geometric (Bezier) reference via the same overlay path the
  // revert uses (a no-op overlay recomputes the arc), so the revert check is an
  // apples-to-apples comparison.
  await page.evaluate(() => window.__NADOC_DBG__.designRenderer.applyFemPositions([]))
  await page.waitForTimeout(100)
  const before = (await page.evaluate(readBeads, strandIds))
    .filter((b) => b.xoId === xoId).sort((a, b) => a.k - b.k)
  expect(before.length, 'this crossover should have its extra-base beads built').toBe(n)

  // Push a simulation frame for this crossover, far from the arc.
  const simTargets = Array.from({ length: n }, (_, k) => [50 + 2 * k, 50, 50])
  await page.evaluate(({ xoId, targets }) => {
    const updates = targets.map((p, k) => ({
      helix_id: '__xb__', bp_index: xoId, direction: k,
      backbone_position: p, nx: 0, ny: 0, nz: 1,
    }))
    window.__NADOC_DBG__.designRenderer.applyFemPositions(updates)
  }, { xoId, targets: simTargets })
  await page.waitForTimeout(100)

  const sim = (await page.evaluate(readBeads, strandIds))
    .filter((b) => b.xoId === xoId).sort((a, b) => a.k - b.k)
  for (let k = 0; k < n; k++) {
    const atTarget = Math.hypot(...sim[k].pos.map((c, i) => c - simTargets[k][i]))
    expect(atTarget, `bead ${k} should sit at its simulated position`).toBeLessThan(0.01)
    const moved = Math.hypot(...sim[k].pos.map((c, i) => c - before[k].pos[i]))
    expect(moved, `bead ${k} should have moved off the arc`).toBeGreaterThan(10)
  }

  // Clearing the overlay reverts the beads to the geometric arc.
  await page.evaluate(() => window.__NADOC_DBG__.designRenderer.applyFemPositions(null))
  await page.waitForTimeout(100)
  const after = (await page.evaluate(readBeads, strandIds))
    .filter((b) => b.xoId === xoId).sort((a, b) => a.k - b.k)
  for (let k = 0; k < n; k++) {
    const d = Math.hypot(...after[k].pos.map((c, i) => c - before[k].pos[i]))
    expect(d, `bead ${k} should revert to the arc`).toBeLessThan(0.01)
  }
})
