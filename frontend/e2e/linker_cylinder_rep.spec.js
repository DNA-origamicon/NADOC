/**
 * Linker cylinder-rep verification (manual/visual).
 *
 * Opens designs through the launcher, switches to the Cylinders representation,
 * and reports the linker cylinder meshes (binding half-cylinders + bridge
 * cylinder) plus a screenshot. Run with:
 *   npx playwright test e2e/linker_cylinder_rep.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'

async function openFromLauncher(page, name) {
  await page.goto('/')
  await page.locator('.lib-file-row').first().waitFor({ timeout: 20_000 })
  const row = page.locator('.lib-file-row', { hasText: name }).first()
  // These verification designs live in the user's workspace and may be absent
  // on another machine — skip rather than hard-fail the suite.
  if (await row.count() === 0) return false
  await row.click()
  // Wait until the scene actually has rendered geometry (a populated cylinder
  // or bead instanced mesh) — large parts take several seconds to build, and
  // switching rep before the helix controller exists is a no-op.
  await page.waitForFunction(() => {
    const s = window.__NADOC_DBG__?.scene
    if (!s) return false
    let ok = false
    s.traverse(o => { if ((o.name === 'helixCylinders' || o.name === 'iFwdBackbone' || o.isInstancedMesh) && o.count > 0) ok = true })
    return ok
  }, { timeout: 40_000 }).catch(() => {})
  await page.waitForTimeout(1500)
  return true
}

async function switchToCylinders(page) {
  await page.evaluate(() => document.getElementById('menu-view-detail-cylinders')?.click())
  // Poll until cylinders are actually visible (rep switch applied). In the
  // assembly the parts are GPU-instanced so `helixCylinders` is count-0 there;
  // accept the linker bridge cylinder becoming visible as the ready signal too.
  await page.waitForFunction(() => {
    const s = window.__NADOC_DBG__?.scene
    if (!s) return false
    let vis = false
    s.traverse(o => {
      if ((o.name === 'helixCylinders' || o.name === 'linkerBridgeCylinders') && o.count > 0 && o.visible) vis = true
    })
    return vis
  }, { timeout: 12_000 }).catch(() => {})
  await page.waitForTimeout(1000)
}

/** Frame the camera on a named instanced mesh's instance for a close-up. */
async function zoomToMesh(page, meshName, dist = 14, inst = 0) {
  await page.evaluate(({ meshName, dist, inst }) => {
    const dbg = window.__NADOC_DBG__
    const THREE = dbg.THREE
    let mesh = null
    dbg.scene.traverse(o => { if (o.name === meshName && o.count > inst) mesh = o })
    if (!mesh) return
    const m = new THREE.Matrix4(); mesh.getMatrixAt(inst, m)
    const pos = new THREE.Vector3().setFromMatrixPosition(m).applyMatrix4(mesh.matrixWorld)
    const up = dbg.camera.up
    dbg.animateCameraTo?.({
      position: [pos.x + dist, pos.y + dist * 0.6, pos.z + dist],
      target: [pos.x, pos.y, pos.z],
      up: [up.x, up.y, up.z],
      duration: 300,
    })
  }, { meshName, dist, inst })
  await page.waitForTimeout(900)
}

/** Count visible slab ('baseSlabs') instances across the whole scene. */
async function countVisibleSlabs(page) {
  return await page.evaluate(() => {
    const s = window.__NADOC_DBG__?.scene
    if (!s) return -1
    let total = 0
    s.traverse(o => { if (o.name === 'baseSlabs' && o.visible) total += (o.count || 0) })
    return total
  })
}

/** Walk the Three scene, summarize the linker cylinder meshes anywhere in graph. */
async function inspectLinkerMeshes(page) {
  return await page.evaluate(() => {
    const dbg = window.__NADOC_DBG__
    if (!dbg?.scene) return { error: 'no scene' }
    const want = new Set(['linkerBindingCylinders', 'linkerBridgeCylinders', 'overhangCylinders', 'helixCylinders'])
    const found = {}
    dbg.scene.traverse((o) => {
      if (want.has(o.name)) {
        found[o.name] = found[o.name] ?? []
        found[o.name].push({ count: o.count, visible: o.visible })
      }
    })
    return found
  })
}

test.describe('Linker cylinder rep', () => {
  test('polymer hinge part (ds linker) — binding halves + bridge', async ({ page }) => {
    test.setTimeout(90_000)
    test.skip(!(await openFromLauncher(page, 'Ultimate Polymer Hinge')), 'design not in workspace')
    await switchToCylinders(page)
    const meshes = await inspectLinkerMeshes(page)
    console.log('POLYMER HINGE (cylinders):', JSON.stringify(meshes))
    await zoomToMesh(page, 'linkerBridgeCylinders', 16)
    await page.screenshot({ path: 'e2e/screenshots/polymer_hinge_cyl.png', clip: { x: 40, y: 30, width: 940, height: 690 } })
    expect(meshes.linkerBindingCylinders, 'binding mesh present').toBeTruthy()
    expect(meshes.linkerBridgeCylinders, 'bridge mesh present').toBeTruthy()
  })

  test('dsdna-link-sel-test part — binding halves + bridge', async ({ page }) => {
    test.skip(!(await openFromLauncher(page, 'dsdna-link-sel-test')), 'design not in workspace')
    await switchToCylinders(page)
    const meshes = await inspectLinkerMeshes(page)
    console.log('DSDNA-LINK-SEL (cylinders):', JSON.stringify(meshes))
    const clip = { x: 40, y: 30, width: 940, height: 690 }
    await zoomToMesh(page, 'linkerBridgeCylinders', 8)
    await page.screenshot({ path: 'e2e/screenshots/linker_cyl_dsdna.png', clip })
    await zoomToMesh(page, 'linkerBindingCylinders', 4, 0)
    await page.screenshot({ path: 'e2e/screenshots/linker_cyl_binding0.png', clip })
    await zoomToMesh(page, 'linkerBindingCylinders', 4, 1)
    await page.screenshot({ path: 'e2e/screenshots/linker_cyl_binding1.png', clip })
    expect(meshes.linkerBindingCylinders, 'binding mesh present').toBeTruthy()
    expect(meshes.linkerBridgeCylinders, 'bridge mesh present').toBeTruthy()
  })

  test('Linker_Assem_test2 assembly — cross-part linker', async ({ page }) => {
    test.setTimeout(90_000)
    test.skip(!(await openFromLauncher(page, 'Linker_Assem_test2')), 'assembly not in workspace')
    // Assemblies default to cylinders on load — wait for the bridge cylinder to
    // become visible rather than re-clicking (lighter on the WebGL context).
    await page.waitForFunction(() => {
      const s = window.__NADOC_DBG__?.scene
      if (!s) return false
      let vis = false
      s.traverse(o => { if (o.name === 'linkerBridgeCylinders' && o.count > 0 && o.visible) vis = true })
      return vis
    }, { timeout: 20_000 }).catch(() => {})
    await page.waitForTimeout(1500)
    const meshes = await inspectLinkerMeshes(page)
    console.log('LINKER ASSEMBLY (cylinders):', JSON.stringify(meshes))
    const clip = { x: 40, y: 30, width: 940, height: 690 }
    await zoomToMesh(page, 'linkerBridgeCylinders', 10)
    await page.screenshot({ path: 'e2e/screenshots/linker_assem_bridge.png', clip })
    // Assert the linker cylinders are actually visible at the assembly's default rep.
    const vis = (meshes.linkerBridgeCylinders ?? []).some(m => m.count > 0 && m.visible)
    expect(vis, 'assembly bridge cylinder visible').toBeTruthy()
  })

  test('Linker_Assem_test2 assembly — beads rep hides slabs', async ({ page }) => {
    test.setTimeout(90_000)
    test.skip(!(await openFromLauncher(page, 'Linker_Assem_test2')), 'assembly not in workspace')
    // Switch to the Beads representation (assembly default is cylinders).
    await page.evaluate(() => document.getElementById('menu-view-detail-beads')?.click())
    // Wait for the rebuild → rebuildLinkers chain (batchPatch → currentAssembly change).
    await page.waitForFunction(() => {
      const s = window.__NADOC_DBG__?.scene
      if (!s) return false
      let beads = false
      s.traverse(o => { if (o.name === 'backboneSpheres' && o.count > 0 && o.visible) beads = true })
      return beads
    }, { timeout: 25_000 }).catch(() => {})
    await page.waitForTimeout(2000)
    const slabs = await countVisibleSlabs(page)
    console.log('ASSEMBLY BEADS — visible slab instances:', slabs)
    await page.screenshot({ path: 'e2e/screenshots/linker_assem_beads.png', clip: { x: 40, y: 30, width: 940, height: 690 } })
    expect(slabs, 'no slabs visible in beads rep').toBe(0)
  })
})
