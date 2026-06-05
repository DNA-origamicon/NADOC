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
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })

  // Load into THIS tab's document: the in-tab api client auto-stamps
  // X-NADOC-Doc, so the design lands in the doc the tab is reading. A
  // default-doc `page.request.post` would load into a different document
  // (multi-doc) and the tab would still see the empty New-Part design.
  //
  // Hinge.nadoc ships overhangs OH1/OH2 + a cluster joint but NO binding
  // (the fixture lost its bundled OverhangBinding), so build one in-tab to
  // keep this spec self-contained. Creating a binding requires the two
  // sub-domains to be Watson-Crick complementary, so OH2's sub-domain gets
  // OH1's reverse complement before the bind.
  await page.evaluate(async (hingePath) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(hingePath)
    const { store } = await import('/src/state/store.js')
    const des = store.getState().currentDesign
    const oh1 = des.overhangs.find(o => o.label === 'OH1')
    const oh2 = des.overhangs.find(o => o.label === 'OH2')
    const rc = s => s.split('').reverse()
      .map(c => ({ A: 'T', T: 'A', G: 'C', C: 'G', N: 'N' }[c])).join('')
    await api._request('PATCH',
      `/design/overhang/${oh2.id}/sub-domains/${oh2.sub_domains[0].id}`,
      { sequence_override: rc(oh1.sequence) })
    const resp = await api._request('POST', '/design/overhang-bindings', {
      sub_domain_a_id: oh1.sub_domains[0].id,
      sub_domain_b_id: oh2.sub_domains[0].id,
      target_joint_id: des.cluster_joints[0].id,
    })
    await api._syncFromDesignResponse(resp)
  }, HINGE_NADOC)
}

test('undo after relax_bond returns beads to PRE position (no 2x rotation)', async ({ page }) => {
  // Generous: File>New + in-tab Hinge load + binding build + bind/relax/undo
  // each round-trips the backend and the relax animates a cluster rotation.
  test.setTimeout(120_000)

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

    // The binding carries its target joint directly (target_joint_id). The
    // old driven_overhang_id/driver_overhang_id → cluster → joint walk used
    // fields the binding model no longer exposes.
    const jointId = binding.target_joint_id ?? d2.cluster_joints[0]?.id
    if (!jointId) throw new Error('no joint on binding')
    return { xoId: xo.id, jointId }
  })

  console.log(`[probe] setup: xo=${setup.xoId.slice(0,8)} joint=${setup.jointId.slice(0,8)}`)

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
