import { test, expect } from '@playwright/test'

// [[overhang-duplex-cluster]] P2 — the Move/Rotate pivot dropdown for an overhang-duplex
// cluster must let the user pick a NON-CENTROID rotation point (each overhang's ROOT bead)
// and HOLD that selection. Two regressions this pins:
//   (1) the <select> reverted to "centroid" after selection (the joints-changed store
//       subscriber rebuilt the options and dropped the value), and
//   (2) the pivot silently snapped back to the visual centroid (refreshClusterPivotForAttach
//       recomputed the centroid and queued it as a pending gizmo transform).
// Fixture: workspace/2x2_OH_test.nadoc — two applied overhang connections → a "Duplex 1"
// cluster (materialized on load).
const FIXTURE = '/home/joshua/NADOC/workspace/2x2_OH_test.nadoc'

test('duplex rotation-point dropdown holds a root pivot + moves the pivot off the centroid', async ({ page }) => {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await page.goto('/')
  await page.waitForTimeout(1500)

  // Load the fixture — the load path materializes the duplex cluster.
  await page.evaluate(async (p) => {
    const a = await import('/src/api/client.js')
    await a.loadDesign(p)
    await a.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await page.waitForTimeout(1200)

  // Find the duplex cluster (carries overhang_duplex_driver_id).
  const duplex = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    const cl = (d?.cluster_transforms ?? []).find(c => c.overhang_duplex_driver_id)
    return cl ? { id: cl.id, pivot: cl.pivot } : null
  })
  expect(duplex, 'a duplex cluster exists after load').not.toBeNull()

  // Activate the DESIGN Move/Rotate tool on the duplex cluster (real entry point).
  const armed = await page.evaluate((id) => window.__nadocTest.activateDesignMoveTool(id), duplex.id)
  expect(armed.active, 'move/rotate tool armed').toBe(true)
  // Pivot dropdown offers centroid + each overhang's root.
  expect(armed.pivotOptions).toContain('centroid')
  const rootOpts = armed.pivotOptions.filter(v => v.startsWith('dup:root:'))
  expect(rootOpts.length, `root options present among ${JSON.stringify(armed.pivotOptions)}`).toBe(2)
  const chosen = rootOpts[0]

  // The backend candidate points (doc-aware client — a raw fetch would hit the default doc).
  const pts = await page.evaluate(async (id) => {
    const a = await import('/src/api/client.js')
    return a.getClusterRotationPoints(id)
  }, duplex.id)
  const chosenRoot = pts.find(p => p.kind === 'overhang_root' && `dup:root:${p.overhang_id}` === chosen)
  const centroid = pts.find(p => p.kind === 'centroid')
  expect(chosenRoot, 'backend has a root rotation-point for the chosen overhang').toBeTruthy()
  expect(centroid, 'backend has a centroid rotation-point').toBeTruthy()

  // Helper: select an option in the REAL sidebar <select>, then read {dropdown value, cluster pivot}.
  const pickAndRead = async (optValue) => {
    await page.evaluate((opt) => {
      const sel = document.getElementById('mr-pivot-sel')
      sel.value = opt
      sel.dispatchEvent(new Event('change'))
    }, optValue)
    await page.waitForTimeout(900)   // round-trip + store subscribers + gizmo re-attach
    return page.evaluate(async (id) => {
      const { store } = await import('/src/state/store.js')
      const cl = store.getState().currentDesign.cluster_transforms.find(c => c.id === id)
      return { value: window.__nadocTest.getMoveRotatePivotState().value, pivot: cl.pivot }
    }, duplex.id)
  }
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])

  // ── Select a ROOT: dropdown HOLDS it (regression 1) + pivot lands on the root bead (regression 2).
  const atRoot = await pickAndRead(chosen)
  expect(atRoot.value, `dropdown held ${chosen} (not centroid)`).toBe(chosen)
  expect(dist(atRoot.pivot, chosenRoot.point),
    `pivot at the root bead (got ${JSON.stringify(atRoot.pivot)}, want ${JSON.stringify(chosenRoot.point)})`).toBeLessThan(1e-3)

  // ── Switch to CENTROID: dropdown holds it + pivot moves to the (distinct) centroid.
  const atCentroid = await pickAndRead('centroid')
  expect(atCentroid.value, 'dropdown switched to centroid').toBe('centroid')
  expect(dist(atCentroid.pivot, centroid.point), 'pivot at the centroid').toBeLessThan(1e-3)
  // The two pivots are genuinely different points — the dropdown drives a real change.
  expect(dist(chosenRoot.point, centroid.point), 'root and centroid are distinct points').toBeGreaterThan(0.1)
  expect(dist(atRoot.pivot, atCentroid.pivot), 'pivot actually moved between the two selections').toBeGreaterThan(0.1)

  await page.screenshot({ path: 'e2e/screenshots/duplex_rotation_point.png', fullPage: true })
  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
