import { test, expect } from '@playwright/test'
import path from 'node:path'

// Persistent inventory: __e2e__SweepScaffold-{mode} parts and hidden revision
// stores are removed by global-teardown.js, including after failures. The
// isolated Playwright backend disables session caching. Retained review evidence:
// .development-artifacts/sweep-scaffold-seamed.png and sweep-scaffold-seamless.png.
// No user file is loaded or modified: these are the original Sweep_test.nadoc
// bundle/sweep authoring parameters, recreated through the public API.
const originalCells = [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]]
const sweptCells = [[1, 2], [0, 3], [0, 2], [0, 1], [1, 1], [1, 3], [1, 4], [1, 5], [0, 5], [0, 4]]
const points = [[0, 0, 0], [0, 9.198, 22.928], [-14.455, 34.91, 27.109]]

async function interfaceState(page) {
  return page.evaluate(async () => {
    const d = (await import('/src/state/store.js')).store.getState().currentDesign
    const helices = new Map(d.helices.map(h => [h.id, h]))
    const strandTypes = new Map(d.strands.map(s => [s.id, s.strand_type]))
    const atInterface = (a, b) => {
      if (a.helix_id === b.helix_id || Math.min(a.bp_index, b.bp_index) !== 62 || Math.max(a.bp_index, b.bp_index) !== 63) return false
      const ha = helices.get(a.helix_id), hb = helices.get(b.helix_id)
      return ha?.grid_pos?.[0] === hb?.grid_pos?.[0] && ha?.grid_pos?.[1] === hb?.grid_pos?.[1]
    }
    const hops = []
    for (const strand of d.strands) {
      for (let i = 1; i < strand.domains.length; i++) {
        const a = strand.domains[i - 1], b = strand.domains[i]
        if (atInterface({ ...a, bp_index: a.end_bp }, { ...b, bp_index: b.start_bp })) {
          hops.push(`${strand.strand_type}:${a.helix_id}:${a.end_bp}:${a.direction}>${b.helix_id}:${b.start_bp}:${b.direction}`)
        }
      }
    }
    const renderer = window.__nadocDR
    const bonds = renderer.getHelixCtrl().coneEntries.filter(c => atInterface(c.fromNuc, c.toNuc))
    const visibleOrdinary = bonds.filter(c => {
      const m = c.instMesh.instanceMatrix.array, offset = c.id * 16
      return !c.isCrossHelix && Math.hypot(m[offset], m[offset + 1], m[offset + 2]) > 0
    })
    return {
      scaffolds: d.strands.filter(s => s.strand_type === 'scaffold' && !s.is_reference).length,
      forcedLigations: d.forced_ligations.length,
      hops: hops.sort(),
      interfaceBonds: bonds.length,
      ordinaryBonds: bonds.filter(c => !c.isCrossHelix).length,
      scaffoldCones: visibleOrdinary.filter(c => strandTypes.get(c.strandId) === 'scaffold').length,
      stapleCones: visibleOrdinary.filter(c => strandTypes.get(c.strandId) === 'staple').length,
      interfaceArcs: renderer.getCrossHelixConnections().filter(c => atInterface(c.fromNuc, c.toNuc)).length,
      staples: d.strands.filter(s => s.strand_type === 'staple').map(s => ({ id: s.id, domains: s.domains })),
    }
  })
}

async function reloadExport(page) {
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const response = await fetch('/api/design/export', {
      headers: { 'X-NADOC-Doc': new URLSearchParams(location.search).get('doc') },
    })
    if (!response.ok || !await api.importDesign(await response.text())) throw new Error('Sweep scaffold reload failed')
  })
}

for (const mode of ['seamed', 'seamless']) {
  test(`Sweep 6-to-10 continuation keeps all duplex bonds through ${mode} routing and reload`, async ({ page }) => {
    test.setTimeout(240_000)
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    page.on('response', r => { if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`) })
    await page.goto(`/?test=1&doc=__e2e__sweep-scaffold-${mode}`)
    await expect(page.locator('#canvas')).toBeVisible()
    await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
    await page.click('#menu-file-new')
    await page.fill('#new-design-name', `__e2e__SweepScaffold-${mode}`)
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
    await page.evaluate(async ({ mode, originalCells }) => {
      const api = await import('/src/api/client.js')
      if (!await api.createBundle({ cells: originalCells, lengthBp: 63, name: `__e2e__SweepScaffold-${mode}` })) throw new Error('Bundle creation failed')
    }, { mode, originalCells })
    await expect.poll(() => page.evaluate(() => new Set(window.__nadocDR.getBackboneEntries().map(e => e.nuc.helix_id)).size), { timeout: 60_000 }).toBe(6)
    await expect(page.locator('#op-progress')).not.toBeVisible({ timeout: 60_000 })
    const shape = await page.evaluate(async ({ sweptCells, points }) => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      if (!await api.createSweep({ cells: sweptCells, points_nm: points, source_helix_id: 'h_XY_1_2', source_end: 'end' })) throw new Error('Sweep creation failed')
      const d = store.getState().currentDesign
      return { helices: d.helices.length, sweptLengths: d.helices.filter(h => h.bp_start === 63).map(h => h.length_bp) }
    }, { sweptCells, points })
    expect(shape).toEqual({ helices: 16, sweptLengths: Array(10).fill(168) })
    await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
    await page.locator('#canvas').focus()
    await page.keyboard.press('f')
    // The API resolves before all presentation/animation updates have finished.
    // Wait for the actual cone instances in the full representation.
    await expect.poll(() => interfaceState(page), { timeout: 60_000 }).toMatchObject({
      interfaceBonds: 12, ordinaryBonds: 12, scaffoldCones: 6, stapleCones: 6,
    })
    const baseline = await interfaceState(page)
    expect(baseline.hops).toHaveLength(12)
    expect(baseline).toMatchObject({ scaffolds: 10, forcedLigations: 0, scaffoldCones: 6, stapleCones: 6, interfaceArcs: 0 })
    // The same loader used for saved .nadoc files must retain ordinary joins.
    await reloadExport(page)
    await expect.poll(() => interfaceState(page), { timeout: 60_000 }).toEqual(baseline)

    await page.locator('#menu-item-tools').hover()
    await page.locator('#menu-item-tools .submenu-item').filter({ hasText: /^Routing/ }).hover()
    await page.click('#menu-routing-scaffold-ends')
    await expect(page.locator('#autoscaffold-modal')).toBeVisible()
    await page.locator(`input[name="as-mode"][value="${mode}"]`).check()
    const response = page.waitForResponse(r => r.url().endsWith(`/design/auto-scaffold-${mode}`))
    await page.click('#as-run')
    expect((await response).ok()).toBe(true)
    await expect(page.locator('#op-progress')).not.toBeVisible({ timeout: 60_000 })
    await expect.poll(async () => (await interfaceState(page)).scaffolds, { timeout: 60_000 }).toBe(1)
    const routed = await interfaceState(page)
    expect(routed).toMatchObject({ forcedLigations: 0, scaffoldCones: 6, stapleCones: 6, interfaceArcs: 0 })
    expect(routed.hops).toEqual(baseline.hops)
    expect(routed.staples).toEqual(baseline.staples)
    await reloadExport(page)
    await expect.poll(() => interfaceState(page), { timeout: 60_000 }).toEqual(routed)
    await page.locator('#canvas').focus()
    await page.keyboard.press('f')
    await page.screenshot({ path: path.resolve(import.meta.dirname, `../../.development-artifacts/sweep-scaffold-${mode}.png`) })
    expect(errors).toEqual([])
  })
}
