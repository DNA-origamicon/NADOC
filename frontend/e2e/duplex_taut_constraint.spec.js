import { test, expect } from '@playwright/test'

// [[overhang-duplex-cluster]] P3 — the free-until-taut ("Constrained (taut bonds)") drag mode.
// This spec pins the risky INTEGRATION: the backend duplex-tether endpoint → doc-aware client →
// the 'helix:bp:DIRECTION' anchor-key format the gizmo's ssDNA projector resolves. If any of
// those disagree, resolveWorldPos returns null and the tether is silently dropped (no constraint,
// the drag would overstretch). We assert every tether anchor resolves to a real backbone bead and
// that selecting the mode arms the gizmo. The actual PBD drag stability stays a human-eye check.
const FIXTURE = '/home/joshua/NADOC/workspace/2x2_OH_test.nadoc'

test('duplex taut-constraint: bond tethers resolve to real beads + the mode arms the gizmo', async ({ page }) => {
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
    const cl = store.getState().currentDesign.cluster_transforms.find(c => c.overhang_duplex_driver_id)
    return cl ? { id: cl.id } : null
  })
  expect(duplex, 'a duplex cluster exists').not.toBeNull()

  // Endpoint (doc-aware) → tethers, and every anchor must match a real geometry bead by the
  // exact key triple the gizmo resolver splits ('helix:bp:direction').
  const resolved = await page.evaluate(async (id) => {
    const a = await import('/src/api/client.js')
    const tethers = await a.getClusterDuplexTethers(id)
    await a.getGeometry()   // sync store geometry, then read the bead set back from it
    const { store } = await import('/src/state/store.js')
    const nucs = store.getState().currentGeometry ?? []
    const hit = (anc) => nucs.some(n => n.helix_id === anc.helix_id && n.bp_index === anc.bp && n.direction === anc.direction)
    return {
      count: tethers.length,
      allResolve: tethers.every(t => hit(t.moving) && hit(t.fixed)),
      contours: tethers.map(t => t.contour_nm),
    }
  }, duplex.id)
  expect(resolved.count, 'monovalent duplex → two bond tethers').toBe(2)
  expect(resolved.allResolve, 'every tether anchor resolves to a real bead').toBe(true)
  expect(resolved.contours.every(c => c > 0 && c < 1)).toBe(true)   // ~0.67 nm backbone bond

  // Activate the duplex cluster's Move/Rotate tool + select the taut-constraint pivot option;
  // the option must exist and the change handler must not throw.
  const armed = await page.evaluate((id) => window.__nadocTest.activateDesignMoveTool(id), duplex.id)
  expect(armed.pivotOptions, `options: ${JSON.stringify(armed.pivotOptions)}`).toContain('dup:taut')

  await page.evaluate(() => {
    const sel = document.getElementById('mr-pivot-sel')
    sel.value = 'dup:taut'
    sel.dispatchEvent(new Event('change'))
  })
  await page.waitForTimeout(600)
  // Selecting it holds (no revert) and produced no console error.
  const val = await page.evaluate(() => window.__nadocTest.getMoveRotatePivotState().value)
  expect(val).toBe('dup:taut')

  await page.screenshot({ path: 'e2e/screenshots/duplex_taut_constraint.png', fullPage: true })
  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
