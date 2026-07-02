import { test, expect } from '@playwright/test'

// Troubleshooting spec ([[overhang-duplex-cluster]] follow-up): when the Move/Rotate tool
// opens on an overhang-DUPLEX cluster, the gizmo handles must render AT the pivot the tool
// rotates about, and a +45° quick-rotate must rotate the duplex beads ABOUT that pivot
// (distance-to-pivot preserved), NOT teleport the cluster to a distant location.
// Fixture: workspace/2x2_OH_test.nadoc → "Duplex 1" cluster (materialized on load).
const FIXTURE = '/home/joshua/NADOC/workspace/2x2_OH_test.nadoc'
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])

test('duplex Move/Rotate: gizmo sits at its pivot and +45° rotates about it (no teleport)', async ({ page }) => {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await page.goto('/')
  await page.waitForTimeout(1500)

  await page.evaluate(async (p) => {
    const a = await import('/src/api/client.js')
    await a.loadDesign(p)
    await a.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await page.waitForTimeout(1200)

  const duplex = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    const cl = (d?.cluster_transforms ?? []).find(c => c.overhang_duplex_driver_id)
    return cl ? { id: cl.id } : null
  })
  expect(duplex, 'a duplex cluster exists after load').not.toBeNull()

  // Activate the DESIGN Move/Rotate tool on the duplex (real entry point).
  const armed = await page.evaluate((id) => window.__nadocTest.activateDesignMoveTool(id), duplex.id)
  expect(armed.active, 'move/rotate tool armed').toBe(true)

  // ── (1) Gizmo handles render ON the duplex (not teleported to empty space) ────
  const before = await page.evaluate((id) => window.__nadocTest.getClusterGizmoState(id), duplex.id)
  expect(before.beadCount, 'duplex has rendered beads').toBeGreaterThan(0)
  console.log('[duplex-gizmo] pivot        =', JSON.stringify(before.pivot))
  console.log('[duplex-gizmo] gizmoPos     =', JSON.stringify(before.gizmoPos))
  console.log('[duplex-gizmo] beadCentroid =', JSON.stringify(before.beadCentroid))
  console.log('[duplex-gizmo] gizmo→beads  =', dist(before.gizmoPos, before.beadCentroid).toFixed(3), 'nm')
  console.log('[duplex-gizmo] gizmo→pivot  =', dist(before.gizmoPos, before.pivot).toFixed(3), 'nm')
  console.log('[duplex-gizmo] pivot→beads  =', dist(before.pivot, before.beadCentroid).toFixed(3), 'nm')
  // The gizmo must sit near the duplex it controls — a teleport put it >10 nm away.
  const gizmoToBeads = dist(before.gizmoPos, before.beadCentroid)
  expect(gizmoToBeads,
    `gizmo at ${JSON.stringify(before.gizmoPos)} vs duplex bead centroid ${JSON.stringify(before.beadCentroid)} (Δ=${gizmoToBeads.toFixed(2)} nm)`)
    .toBeLessThan(6)
  // The rotation pivot must also sit on the duplex.
  expect(dist(before.pivot, before.beadCentroid), 'pivot on the duplex').toBeLessThan(6)

  // ── (2) +45° rotates the beads ABOUT the gizmo (no teleport) ──────────────────
  // The effective rotation center is the gizmo position C = pivot + translation
  // (q = R·(p−pivot)+pivot+T ⇒ |q−C| = |p−pivot|, constant under R). So beads keep
  // their distance to the GIZMO, and the gizmo/centroid stay put.
  await page.evaluate(() => document.getElementById('mr-rx-inc').click())
  await page.waitForTimeout(400)
  const after = await page.evaluate((id) => window.__nadocTest.getClusterGizmoState(id), duplex.id)
  console.log('[duplex-gizmo] after gizmoPos     =', JSON.stringify(after.gizmoPos))
  console.log('[duplex-gizmo] after beadCentroid =', JSON.stringify(after.beadCentroid))

  // The gizmo (rotation center) is fixed under a rotation.
  expect(dist(after.gizmoPos, before.gizmoPos), 'gizmo/rotation-center fixed under rotation').toBeLessThan(0.1)
  // Every bead keeps its distance to the rotation center → a genuine rotation, not a shear/teleport.
  let maxRadiusErr = 0
  for (let i = 0; i < before.beads.length; i++) {
    const rBefore = dist(before.beads[i], before.gizmoPos)
    const rAfter = dist(after.beads[i], after.gizmoPos)
    maxRadiusErr = Math.max(maxRadiusErr, Math.abs(rBefore - rAfter))
  }
  expect(maxRadiusErr, `max |Δ radius-to-gizmo| across beads = ${maxRadiusErr.toFixed(3)} nm (≈0 for a clean rotation)`).toBeLessThan(0.15)
  // The duplex must have actually MOVED (a +45° turn is not a no-op) but stayed local.
  let maxBeadMove = 0
  for (let i = 0; i < before.beads.length; i++) maxBeadMove = Math.max(maxBeadMove, dist(before.beads[i], after.beads[i]))
  console.log('[duplex-gizmo] max bead move =', maxBeadMove.toFixed(3), 'nm')
  expect(maxBeadMove, 'the +45° actually rotated the duplex').toBeGreaterThan(0.2)
  const centroidJump = dist(after.beadCentroid, before.beadCentroid)
  expect(centroidJump, `centroid moved ${centroidJump.toFixed(2)} nm — a teleport would be tens of nm`).toBeLessThan(3)

  // ── (3) Pick an overhang ROOT pivot, then +45° — gizmo stays on the duplex and
  //         the rotation is clean about the (new) gizmo center, no teleport ────────
  const rootOpt = armed.pivotOptions.find(v => v.startsWith('dup:root:'))
  expect(rootOpt, 'a root pivot option exists').toBeTruthy()
  await page.evaluate((opt) => {
    const sel = document.getElementById('mr-pivot-sel')
    sel.value = opt
    sel.dispatchEvent(new Event('change'))
  }, rootOpt)
  await page.waitForTimeout(1000)
  const atRoot = await page.evaluate((id) => window.__nadocTest.getClusterGizmoState(id), duplex.id)
  console.log('[duplex-gizmo] ROOT pivot         =', JSON.stringify(atRoot.pivot))
  console.log('[duplex-gizmo] ROOT gizmoPos      =', JSON.stringify(atRoot.gizmoPos))
  console.log('[duplex-gizmo] ROOT gizmo→beads   =', dist(atRoot.gizmoPos, atRoot.beadCentroid).toFixed(3), 'nm')
  console.log('[duplex-gizmo] ROOT gizmo→pivot   =', dist(atRoot.gizmoPos, atRoot.pivot).toFixed(3), 'nm')
  // Gizmo still on the duplex (not teleported by the pivot switch).
  expect(dist(atRoot.gizmoPos, atRoot.beadCentroid), 'gizmo on the duplex after root select').toBeLessThan(6)

  await page.evaluate(() => document.getElementById('mr-rx-inc').click())
  await page.waitForTimeout(400)
  const afterRoot = await page.evaluate((id) => window.__nadocTest.getClusterGizmoState(id), duplex.id)
  let maxRootRadiusErr = 0
  for (let i = 0; i < atRoot.beads.length; i++) {
    maxRootRadiusErr = Math.max(maxRootRadiusErr,
      Math.abs(dist(atRoot.beads[i], atRoot.gizmoPos) - dist(afterRoot.beads[i], afterRoot.gizmoPos)))
  }
  console.log('[duplex-gizmo] ROOT +45 max |Δ radius| =', maxRootRadiusErr.toFixed(3), 'nm')
  expect(maxRootRadiusErr, 'root +45 is a clean rotation about the gizmo').toBeLessThan(0.15)
  // No teleport on the root-pivot +45 either.
  let maxRootMove = 0
  for (let i = 0; i < atRoot.beads.length; i++) maxRootMove = Math.max(maxRootMove, dist(atRoot.beads[i], afterRoot.beads[i]))
  console.log('[duplex-gizmo] ROOT +45 max bead move =', maxRootMove.toFixed(3), 'nm')
  expect(maxRootMove, 'root +45 actually rotated the duplex, but locally (no teleport)').toBeGreaterThan(0.2)
  expect(maxRootMove, 'root +45 did not teleport').toBeLessThan(20)

  await page.screenshot({ path: 'e2e/screenshots/duplex_gizmo_pivot.png', fullPage: true })
  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
