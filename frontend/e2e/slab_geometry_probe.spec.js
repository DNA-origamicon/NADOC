/**
 * TROUBLESHOOTING PROBE — not part of the routine loop.
 *
 * Renders `workspace/2hbx1.nadoc` looking straight down the helix axis (+Z toward the
 * camera, so the XY cross-section fills the screen) and screenshots it.  One base pair per
 * helix, one helix per caDNAno cell type, so the two base pairs sit side by side and any
 * cell-type asymmetry in the base slabs is visible directly.
 *
 * Also dumps the opening angle between the rendered slab directions. Slab orientation
 * comes from base_normal projected into the axis-normal plane, not bead-to-base position.
 */
import { test, expect } from '@playwright/test'

const REPO = '/home/joshua/NADOC'
const DESIGN = 'workspace/2hbx1.nadoc'

test.describe('slab geometry probe', () => {
  test('2hbx1 down the Z axis', async ({ page }) => {
    test.setTimeout(120_000)

    await page.goto('/?doc=slabprobe')
    await page.waitForSelector('#canvas')
    await page.evaluate(async (p) => {
      const api = await import('/src/api/client.js')
      await api.loadDesign(p)
    }, `${REPO}/${DESIGN}`)

    // Wait for real geometry rather than guessing a duration.
    await expect.poll(
      () => page.evaluate(async () => {
        const { store } = await import('/src/state/store.js')
        return (store.getState().currentGeometry ?? []).length
      }),
      { timeout: 60_000, message: 'geometry never arrived' },
    ).toBeGreaterThan(0)

    // Overlays sit on top of the canvas after a programmatic load, and an ELEMENT
    // screenshot still composites whatever is painted over that region.
    await page.evaluate(() => {
      document.getElementById('welcome-screen')?.classList.add('hidden')
      for (const el of document.querySelectorAll('div,section,aside')) {
        const t = (el.textContent || '').trim()
        if (t.startsWith('WORKING') || t.startsWith('Working')) el.style.display = 'none'
      }
    })

    // Let any frame-all that follows a load finish BEFORE the camera is placed, or it
    // silently overrides it (first attempt: the Z axis was still visible as a diagonal).
    await page.waitForTimeout(2500)

    const view = await page.evaluate(() => {
      const { camera, controls, THREE, store } = window.__NADOC_DBG__
      const geo = store.getState().currentGeometry ?? []
      const pts = geo.map((n) => new THREE.Vector3(...n.backbone_position))
      const box = new THREE.Box3().setFromPoints(pts)
      const c = box.getCenter(new THREE.Vector3())
      const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1.5)
      // Straight down the helix axis: camera on +Z, +Y up, so the XY cross-section is the
      // screen plane and the two base pairs sit side by side.
      if (controls) controls.target.copy(c)
      camera.position.set(c.x, c.y, c.z + r * 3.2)
      camera.up.set(0, 1, 0)
      camera.lookAt(c)
      camera.updateProjectionMatrix()
      if (controls) controls.update()
      return { centre: c.toArray(), radius: r, nucs: geo.length,
               camZ: camera.position.z, axisDot: camera.getWorldDirection(new THREE.Vector3()).z }
    })
    console.log('view:', JSON.stringify(view))

    await page.waitForTimeout(800)
    // Shoot the WebGL canvas only — no toolbar, no welcome screen, no busy popup.
    await page.locator('#canvas').screenshot({ path: 'e2e/screenshots/slab_probe_z.png' })

    // The same number the picture shows: angle between the two rendered slab directions.
    const angles = await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const geo = store.getState().currentGeometry ?? []
      const byPair = {}
      for (const n of geo) {
        const k = `${n.helix_id}|${n.bp_index}`
        ;(byPair[k] ??= {})[n.direction] = n
      }
      const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
      const len = (a) => Math.sqrt(dot(a, a))
      const projectedNormal = (n) => {
        const t = n.axis_tangent
        const b = n.base_normal
        const tt = dot(t, t)
        const k = tt > 0 ? dot(b, t) / tt : 0
        return [b[0] - k * t[0], b[1] - k * t[1], b[2] - k * t[2]]
      }
      const out = []
      for (const [k, p] of Object.entries(byPair)) {
        if (!p.FORWARD || !p.REVERSE) continue
        const vf = projectedNormal(p.FORWARD)
        const vr = projectedNormal(p.REVERSE)
        out.push({ pair: k, opening: (Math.acos(dot(vf, vr) / (len(vf) * len(vr))) * 180) / Math.PI })
      }
      return out
    })
    console.log('slab openings:', JSON.stringify(angles, null, 1))
  })
})
