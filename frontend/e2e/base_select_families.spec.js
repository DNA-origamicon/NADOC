/**
 * Base-level selection across the FIVE bead families.
 *
 * base_select.spec.js covers the gesture set on ordinary backbone beads. This one proves
 * the other renderers are reachable at all: extra crossover bases (crossover_connections),
 * flexible-ssDNA arc beads (flexible_arcs) and ss-linker bridge beads (overhang_link_arcs)
 * each live in their own InstancedMesh outside `backboneEntries`, and were unpickable
 * before this level existed.
 *
 * Asserts on `__nadocTest.getBaseCandidates()` — the same union a click/lasso resolves
 * against — so "unreachable" and "just missed the click" stay distinguishable.
 *
 * Loads REAL workspace designs (the only place these features occur) read-only.
 * NOT part of the routine dev loop.
 */
import { test, expect } from '@playwright/test'

const REPO = '/home/jojo/Work/NADOC'

/**
 * Load a real .nadoc through the app's OWN load path.
 *
 * `POST /api/design/load` alone is not enough: it sets the design server-side, but the
 * frontend's boot does not adopt an existing design for a `?doc=` session — the welcome
 * screen stays up and the store stays empty. Calling `api.loadDesign()` in-page is the
 * same call the command palette's Load makes, and it populates the store.
 */
async function loadWorkspaceDesign(page, doc, relPath) {
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  await page.evaluate(async (p) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(p)
  }, `${REPO}/${relPath}`)
  // The exotic bead families are built by late renderers (crossover_connections,
  // flexible_arcs, overhang_link_arcs) — poll for beads rather than guessing a duration.
  await expect.poll(
    () => page.evaluate(() => window.__nadocTest.getBaseCandidates().length),
    { timeout: 25_000, message: `no base candidates ever appeared for ${relPath}` },
  ).toBeGreaterThan(0)
}

/** Candidate counts per family. */
async function familyCounts(page) {
  return page.evaluate(() => {
    const out = {}
    for (const c of window.__nadocTest.getBaseCandidates()) {
      out[c.family] = (out[c.family] ?? 0) + 1
    }
    return out
  })
}

const keysOf = (page, family) => page.evaluate(
  (f) => window.__nadocTest.getBaseCandidates().filter(c => c.family === f).map(c => c.key), family)

test.describe('Base-level candidates across bead families', () => {
  test('extra crossover bases are enumerable and keyed __xb__:<xoId>:<k>', async ({ page }) => {
    await loadWorkspaceDesign(page, 'e2e-fam-xb', 'workspace/6hbS42_1xT.nadoc')
    const counts = await familyCounts(page)
    expect(counts.backbone, 'backbone beads present').toBeGreaterThan(0)
    expect(counts.xover, 'this design has extra crossover bases').toBeGreaterThan(0)

    const keys = await keysOf(page, 'xover')
    expect(keys.every(k => k.startsWith('__xb__:')), 'extra bases use the repo __xb__ form').toBe(true)
    expect(new Set(keys).size, 'each extra base has a distinct key').toBe(keys.length)
  })

  test('ss-linker bridge beads are enumerable and keyed __lnk__<connId>:<slot>', async ({ page }) => {
    await loadWorkspaceDesign(page, 'e2e-fam-lnk', 'workspace/Ultimate Polymer Hinge 191016.nadoc')
    const counts = await familyCounts(page)
    expect(counts.backbone, 'backbone beads present').toBeGreaterThan(0)
    expect(counts.sslink, 'this design has an ss linker').toBeGreaterThan(0)

    const keys = await keysOf(page, 'sslink')
    expect(keys.every(k => k.startsWith('__lnk__')), 'linker bases use the __lnk__ helix').toBe(true)
    expect(new Set(keys).size, 'each linker slot has a distinct key').toBe(keys.length)
  })

  test('every candidate key parses back to a base, with no cross-family collisions', async ({ page }) => {
    await loadWorkspaceDesign(page, 'e2e-fam-parse', 'workspace/6hbS42_1xT.nadoc')
    const bad = await page.evaluate(async () => {
      const { parseBaseKey, baseFamily } = await import('/src/scene/base_ref.js')
      const seen = new Map()
      const problems = []
      for (const c of window.__nadocTest.getBaseCandidates()) {
        if (!parseBaseKey(c.key)) problems.push(`unparseable: ${c.key}`)
        if (!baseFamily(c.key))   problems.push(`no family: ${c.key}`)
        if (seen.has(c.key) && seen.get(c.key) !== c.family) {
          problems.push(`key collision across families: ${c.key}`)
        }
        seen.set(c.key, c.family)
      }
      return problems.slice(0, 10)
    })
    expect(bad, 'every enumerated key round-trips through base_ref').toEqual([])
  })

  test('candidate keys are unique — no two beads share an address', async ({ page }) => {
    await loadWorkspaceDesign(page, 'e2e-fam-uniq', 'workspace/6hbS42_1xT.nadoc')
    const { total, unique } = await page.evaluate(() => {
      const keys = window.__nadocTest.getBaseCandidates().map(c => c.key)
      return { total: keys.length, unique: new Set(keys).size }
    })
    expect(total).toBeGreaterThan(0)
    expect(unique, 'every bead in the scene has its own key').toBe(total)
  })
})
