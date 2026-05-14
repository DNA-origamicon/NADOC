/**
 * Reproduce the undo-after-relax 2x rotation bug.
 *
 * Flow:
 *   1. Load Hinge.nadoc
 *   2. Bind the OverhangBinding so the OH→parent crossover is stretched.
 *   3. Snapshot bead positions (PRE).
 *   4. Trigger relax-bond via API → cluster rotates by ~55°.
 *   5. Snapshot bead positions (POST).
 *   6. Undo via API → cluster should return to PRE.
 *   7. Snapshot bead positions (UNDO).
 *   8. Assert: most beads in UNDO match PRE within tolerance.
 *      If 2x rotation bug exists, UNDO will be very different from PRE.
 */

import { test, expect } from '@playwright/test'
import path from 'path'

const API = 'http://127.0.0.1:8000/api'

const HINGE_NADOC = path.resolve(
  import.meta.dirname ?? __dirname,
  '../../workspace/Hinge.nadoc',
)

async function loadHinge(page) {
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', 'relax-undo-bug')
  await page.click('#new-design-create')
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 10_000 })

  const r = await page.request.post(`${API}/design/load`, {
    data: { path: HINGE_NADOC },
  })
  expect(r.ok()).toBeTruthy()

  await page.evaluate(async () => {
    const apiMod = await import('/src/api/client.js')
    await apiMod.getDesign()
  })
}

test('undo after relax_bond returns beads to PRE position (no 2x rotation)', async ({ page }) => {
  test.setTimeout(60_000)

  const consoleLogs = []
  page.on('console', (msg) => {
    const txt = msg.text()
    if (txt.startsWith('[clusterDelta]') || txt.startsWith('[probe]')) consoleLogs.push(txt)
  })

  await page.goto('/')
  await loadHinge(page)

  // Enable cluster-delta diagnostic logging.
  await page.evaluate(() => { window._nadocClusterDeltaDebug = true })

  // Bind the first OverhangBinding (force false→true cycle for reproducibility).
  const setup = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const apiMod = await import('/src/api/client.js')
    const d0 = store.getState().currentDesign
    let binding = d0.overhang_bindings?.[0]
    if (!binding) throw new Error('no OverhangBinding in design')
    if (binding.bound) {
      await apiMod.patchOverhangBinding(binding.id, { bound: false })
    }
    await apiMod.patchOverhangBinding(binding.id, { bound: true })

    const d2 = store.getState().currentDesign
    binding = d2.overhang_bindings[0]
    const snapXoverIds = new Set((binding.prior_driven_topology?.crossovers ?? []).map(x => x.id))
    const xo = d2.crossovers.find(x => snapXoverIds.has(x.id))
    if (!xo) throw new Error('no OH→parent crossover found in snapshot')

    const helixToCluster = new Map()
    for (const ct of d2.cluster_transforms) {
      for (const hid of ct.helix_ids ?? []) helixToCluster.set(hid, ct.id)
    }
    const ohById = new Map(d2.overhangs.map(o => [o.id, o]))
    const drivenClusterId = helixToCluster.get(ohById.get(binding.driven_overhang_id).helix_id)
    const driverClusterId = helixToCluster.get(ohById.get(binding.driver_overhang_id).helix_id)
    const joint = d2.cluster_joints.find(j =>
      j.cluster_id === drivenClusterId || j.cluster_id === driverClusterId,
    )
    if (!joint) throw new Error('no joint found on either side')
    return { xoId: xo.id, jointId: joint.id, joinClusterId: joint.cluster_id }
  })

  console.log(`[probe] setup: xo=${setup.xoId.slice(0,8)} joint=${setup.jointId.slice(0,8)} cluster=${setup.joinClusterId.slice(0,8)}`)

  // Snapshot PRE bead positions.
  const snapPre = await page.evaluate(() => {
    const snap = window._nadocDebug.snapPos('pre')
    return Array.from(snap.map.entries())
  })

  // Trigger relax via API.
  const relaxInfo = await page.evaluate(async ({ xoId, jointId }) => {
    const apiMod = await import('/src/api/client.js')
    const r = await apiMod.relaxBond(
      { bond_type: 'crossover', bond_id: xoId },
      { jointIds: [jointId] },
    )
    return r?.relax_info
  }, { xoId: setup.xoId, jointId: setup.jointId })
  console.log(`[probe] relax_info: ${JSON.stringify(relaxInfo)}`)

  const snapPost = await page.evaluate(() => {
    const snap = window._nadocDebug.snapPos('post')
    return Array.from(snap.map.entries())
  })

  // Undo via API.
  await page.evaluate(async () => {
    const apiMod = await import('/src/api/client.js')
    await apiMod.undo()
  })

  const snapUndo = await page.evaluate(() => {
    const snap = window._nadocDebug.snapPos('undo')
    return Array.from(snap.map.entries())
  })

  // Compute distances PRE vs UNDO and PRE vs POST.
  const preMap = new Map(snapPre)
  const postMap = new Map(snapPost)
  const undoMap = new Map(snapUndo)

  const distPostFromPre = []
  const distUndoFromPre = []
  for (const [k, p] of preMap) {
    const q = postMap.get(k)
    if (q) {
      const d = Math.sqrt((p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2)
      distPostFromPre.push([k, d])
    }
    const u = undoMap.get(k)
    if (u) {
      const d = Math.sqrt((p[0]-u[0])**2 + (p[1]-u[1])**2 + (p[2]-u[2])**2)
      distUndoFromPre.push([k, d])
    }
  }
  distPostFromPre.sort((a, b) => b[1] - a[1])
  distUndoFromPre.sort((a, b) => b[1] - a[1])

  const maxPostDelta = distPostFromPre[0]?.[1] ?? 0
  const maxUndoDelta = distUndoFromPre[0]?.[1] ?? 0
  console.log(`[probe] max bead Δ PRE→POST = ${maxPostDelta.toFixed(3)} nm (relax rotation magnitude)`)
  console.log(`[probe] max bead Δ PRE→UNDO = ${maxUndoDelta.toFixed(3)} nm (should be ~0)`)

  // Print top 5 most moved beads PRE→UNDO so we can see the bug shape.
  console.log('[probe] top 5 PRE→UNDO drift:')
  for (const [k, d] of distUndoFromPre.slice(0, 5)) {
    const p = preMap.get(k)
    const u = undoMap.get(k)
    console.log(`  ${k} Δ=${d.toFixed(3)} pre=(${p[0].toFixed(2)},${p[1].toFixed(2)},${p[2].toFixed(2)}) undo=(${u[0].toFixed(2)},${u[1].toFixed(2)},${u[2].toFixed(2)})`)
  }

  console.log('--- cluster-delta diagnostics ---')
  for (const m of consoleLogs) console.log(m)

  // If the 2x bug exists, max PRE→UNDO Δ is roughly the same as PRE→POST Δ
  // (the cluster rotated past PRE by ~θ instead of stopping at PRE).
  // After fix, max PRE→UNDO should be ~0.
  expect(maxUndoDelta).toBeLessThan(0.01)
})
