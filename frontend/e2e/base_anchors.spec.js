/**
 * Base-level picks feeding ANCHORS and the OCCUPANCY-CLOUD SCOPE.
 *
 * Both features share one read — `resolveSelectionAnchors` in scene/efield_math.js — so
 * the occupancy scope card is literally the anchor widget with `engine:'occupancy'`.
 * Wiring `multiSelectedBaseKeys` into that function lights up both, plus all six anchor
 * cards (oxDNA, mrDNA, CanDo, SNUPI, NAMD) and the purple halo.
 *
 * Drives the REAL card buttons, not just the pure functions, because the interesting part
 * is the boundary: two of the five bead families the `base` level can pick have no
 * (helix, bp, direction) in the backend strand walk and would resolve to zero particles.
 * Those must be reported, never silently dropped.
 *
 * NOT part of the routine dev loop.
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

/** Load, frame, and zoom until beads are individually addressable (see base_select.spec.js). */
async function loadFramedPart(page, opts) {
  await loadScaffoldedPart(page, opts)
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(500)
  const box = await page.locator('#canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 10; i++) { await page.mouse.wheel(0, -240); await page.waitForTimeout(50) }
  await page.waitForTimeout(600)
  return box
}

/** Engage base level and Ctrl-drag a lasso over the left band of beads. */
async function lassoSomeBases(page, box) {
  await page.locator('#select-filter .sf-btn[data-key="base"]').click()
  await page.waitForTimeout(200)
  const pts = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(400))
  const inb = pts.filter(p => p.x > box.x + 60 && p.x < box.x + box.width - 340 &&
                              p.y > box.y + 80 && p.y < box.y + box.height - 60)
  const xs = inb.map(p => p.x), ys = inb.map(p => p.y)
  await page.keyboard.down('Control')
  await page.mouse.move(Math.min(...xs) - 8, Math.min(...ys) - 8)
  await page.mouse.down()
  await page.mouse.move(Math.min(...xs) + (Math.max(...xs) - Math.min(...xs)) * 0.4,
                        Math.max(...ys) + 8, { steps: 12 })
  await page.mouse.up()
  await page.keyboard.up('Control')
  await page.waitForTimeout(400)
  return (await page.evaluate(() => window.__nadocTest.getSelectedBaseKeys())).length
}

test.describe('Base picks → anchors & occupancy scope', () => {
  test('every lassoed base reaches both the anchor descriptors and the occupancy wire format', async ({ page }) => {
    test.setTimeout(180000)
    const box = await loadFramedPart(page, { doc: 'e2e-base-anchor', name: 'base-anchor' })
    const pool = await lassoSomeBases(page, box)
    expect(pool).toBeGreaterThan(1)

    const r = await page.evaluate(async () => {
      const { resolveSelectionAnchors, anchorSelectionState, anchorsToSelection, unsupportedBaseKeys }
        = await import('/src/scene/efield_math.js')
      const snap = anchorSelectionState({ state: window.__nadocTest.store.getState(), ctrlBeadNucs: [] })
      const anchors = resolveSelectionAnchors(snap)
      return {
        anchors: anchors.length,
        allBase: anchors.every(a => a.kind === 'base'),
        bases: anchorsToSelection(anchors)?.bases ?? [],
        skipped: unsupportedBaseKeys(snap).length,
      }
    })
    expect(r.anchors, 'one anchor descriptor per picked base').toBe(pool)
    expect(r.allBase).toBe(true)
    expect(r.bases.length, 'and the same descriptors reach the occupancy `bases` list').toBe(pool)
    expect(r.bases[0], '[helix_id, bp, direction] triples').toHaveLength(3)
    expect(r.skipped).toBe(0)
  })

  test('the Anchors card Add button turns base picks into chips and lights the halo', async ({ page }) => {
    test.setTimeout(180000)
    const box = await loadFramedPart(page, { doc: 'e2e-base-anchor2', name: 'base-anchor2' })
    const pool = await lassoSomeBases(page, box)
    const before = await page.evaluate(() => window.__nadocTest.anchors.glowCount())

    await page.evaluate(() => document.getElementById('oxdna-anchors-toggle')?.click())
    await page.waitForTimeout(250)
    await page.evaluate(() => document.getElementById('oxdna-anchors-add')?.click())
    await page.waitForTimeout(500)

    const r = await page.evaluate(() => ({
      chips:   document.getElementById('oxdna-anchors-list')?.textContent ?? '',
      status:  document.getElementById('oxdna-anchors-status')?.textContent ?? '',
      anchors: window.__nadocTest.anchors.card?.getAnchors?.().length ?? -1,
      glow:    window.__nadocTest.anchors.glowCount(),
    }))
    expect(r.anchors).toBe(pool)
    expect(r.chips).toContain('base ')
    expect(r.status, 'the count names bases, not strands').toMatch(/fixed bases?\./)
    expect(r.glow, 'purple anchor halo lit').toBeGreaterThan(before)
  })

  test('the occupancy scope card accepts the same base picks', async ({ page }) => {
    test.setTimeout(180000)
    const box = await loadFramedPart(page, { doc: 'e2e-base-occ', name: 'base-occ' })
    const pool = await lassoSomeBases(page, box)

    await page.evaluate(() => document.getElementById('oxdna-occupancy-scope-toggle')?.click())
    await page.waitForTimeout(250)
    await page.evaluate(() => document.getElementById('oxdna-occupancy-scope-add')?.click())
    await page.waitForTimeout(500)

    const chips = await page.evaluate(() =>
      document.getElementById('oxdna-occupancy-scope-list')?.textContent ?? '')
    expect(chips).toContain('base ')
    expect(chips.match(/base /g)?.length).toBe(pool)
  })

  // Staleness, across all three descriptor kinds. The backend resolves a descriptor whose
  // owner is gone to ZERO particles without complaining, so an anchor set that looks added
  // and holds nothing is the failure to avoid.
  test('stale base picks are reported, not silently dropped', async ({ page }) => {
    test.setTimeout(180000)
    await loadScaffoldedPart(page, { doc: 'e2e-base-skip', name: 'base-skip' })
    await page.waitForTimeout(500)

    // One live base + one dead crossover + one dead extension.
    await page.evaluate(() => {
      const h = window.__nadocTest.store.getState().currentDesign?.helices?.[0]?.id
      window.__nadocTest.store.setState({
        multiSelectedBaseKeys: [`${h}:10:FORWARD`, '__xb__:xo-fake:0', '__ext_e-fake:0:FORWARD'],
      })
    })
    await page.evaluate(() => document.getElementById('oxdna-anchors-toggle')?.click())
    await page.waitForTimeout(250)
    await page.evaluate(() => document.getElementById('oxdna-anchors-add')?.click())
    await page.waitForTimeout(400)

    const mixed = await page.evaluate(() => ({
      status: document.getElementById('oxdna-anchors-status')?.textContent ?? '',
      n: window.__nadocTest.anchors.card?.getAnchors?.().length ?? -1,
    }))
    expect(mixed.n, 'only the live base was added').toBe(1)
    expect(mixed.status).toMatch(/skipped 2 stale bases/i)

    await page.evaluate(() => document.getElementById('oxdna-anchors-clear')?.click())
    await page.evaluate(() => window.__nadocTest.store.setState({
      multiSelectedBaseKeys: ['__xb__:xo-fake:0', '__xb__:xo-fake:1'],
    }))
    await page.evaluate(() => document.getElementById('oxdna-anchors-add')?.click())
    await page.waitForTimeout(400)

    const only = await page.evaluate(() => ({
      status: document.getElementById('oxdna-anchors-status')?.textContent ?? '',
      n: window.__nadocTest.anchors.card?.getAnchors?.().length ?? -1,
    }))
    expect(only.n).toBe(0)
    expect(only.status).toMatch(/no longer exist/i)
  })

  // Real extra crossover bases from a real design. They have no (helix, bp, direction) at
  // all, so they travel as `kind:'extra_base'` keyed on (crossover_id, insert index).
  test('picked extra crossover bases become extra_base anchors', async ({ page }) => {
    test.setTimeout(180000)
    await page.goto('/?doc=e2e-base-xb')
    await page.waitForSelector('#canvas')
    await page.evaluate(async (p) => {
      const api = await import('/src/api/client.js')
      await api.loadDesign(p)
    }, '/home/jojo/Work/NADOC/workspace/6hbS42_1xT.nadoc')
    await expect.poll(
      () => page.evaluate(() =>
        window.__nadocTest.getBaseCandidates().filter(c => c.family === 'xover').length),
      { timeout: 25_000, message: 'design never produced extra crossover bases' },
    ).toBeGreaterThan(0)

    const seeded = await page.evaluate(() => {
      const keys = window.__nadocTest.getBaseCandidates()
        .filter(c => c.family === 'xover').slice(0, 3).map(c => c.key)
      window.__nadocTest.store.setState({ multiSelectedBaseKeys: keys })
      return keys
    })
    expect(seeded.every(k => k.startsWith('__xb__:'))).toBe(true)

    const r = await page.evaluate(async () => {
      const { resolveSelectionAnchors, anchorSelectionState, anchorsToSelection, unsupportedBaseKeys }
        = await import('/src/scene/efield_math.js')
      const snap = anchorSelectionState({ state: window.__nadocTest.store.getState(), ctrlBeadNucs: [] })
      const anchors = resolveSelectionAnchors(snap)
      return { anchors, sel: anchorsToSelection(anchors), skipped: unsupportedBaseKeys(snap) }
    })
    expect(r.skipped, 'extra bases are addressable now, nothing skipped').toEqual([])
    expect(r.anchors.every(a => a.kind === 'extra_base')).toBe(true)
    expect(r.sel.extra_bases).toHaveLength(seeded.length)

    await page.evaluate(() => document.getElementById('oxdna-anchors-toggle')?.click())
    await page.waitForTimeout(250)
    await page.evaluate(() => document.getElementById('oxdna-anchors-add')?.click())
    await page.waitForTimeout(400)
    const card = await page.evaluate(() => ({
      chips: document.getElementById('oxdna-anchors-list')?.textContent ?? '',
      n: window.__nadocTest.anchors.card?.getAnchors?.().length ?? -1,
    }))
    expect(card.n).toBe(seeded.length)
    expect(card.chips).toContain('xover base')
  })
})
