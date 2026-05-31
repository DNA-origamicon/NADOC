/**
 * Verifies the Hull Prism of mini_hinge.nadoc renders as TWO spatially-disjoint
 * blocks (one per arm), not one continuous block.
 *
 * Background: _buildExtrusionBoxes in joint_renderer.js was changed to split each
 * feature-log extrusion's `cells` into 4-neighbour lattice-connected components,
 * emitting one box per component. mini_hinge has cells in rows {0,1} and {4,5}
 * (gap at rows 2,3) -> should yield 2 disjoint box volumes. All boxes are still
 * merged into ONE THREE.Mesh, so "two blocks" = two spatially-disjoint vertex
 * clusters within that single merged geometry.
 *
 * Strategy: load the design, enable hull-prism, traverse window.__nadocTest.scene
 * for the extrusion hull mesh(es) (renderOrder===100, transparent MeshPhong),
 * read the merged geometry's per-vertex WORLD positions, and along each of the
 * three principal axes count disjoint bands separated by a gap larger than one
 * helix spacing (~2.6 nm). The arm-separation axis must show exactly 2 bands.
 */

import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'

const API    = 'http://localhost:8000/api'
const DESIGN = '/home/joshua/NADOC/workspace/mini_hinge.nadoc'
const GAP_NM = 2.6   // one HC inter-helix spacing; the mini_hinge gap is ~2 rows

test.describe('Hull prism — disjoint clusters (mini_hinge.nadoc)', () => {
  test.setTimeout(120_000)

  test('renders two spatially-disjoint hull volumes', async ({ page }) => {
    const consoleErrors = []
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()) })
    page.on('pageerror', e => consoleErrors.push('PAGEERROR: ' + e.message))

    // Load the design into the backend (default doc), then open the app.
    // This mirrors the proven hull_prism_curved.spec.js load path.
    const content = readFileSync(DESIGN, 'utf-8')
    const resp = await page.request.post(`${API}/design/import`, { data: { content } })
    expect(resp.ok()).toBeTruthy()

    await page.goto('/')
    // Wait for the scene + a loaded design (beads present) before proceeding.
    await page.waitForFunction(() => !!window.__nadocTest?.scene, { timeout: 20_000 })
    await page.waitForTimeout(2000)

    // Enable hull-prism via the View menu item (id used by hull_prism_curved spec).
    await page.evaluate(() => document.getElementById('menu-view-hull-prism')?.click())
    await page.waitForTimeout(1500)

    // Traverse the scene for the extrusion hull mesh(es) and analyse vertex bands
    // along each principal world axis.
    const result = await page.evaluate(({ gapNm }) => {
      const scene = window.__nadocTest?.scene
      if (!scene) return { error: 'no scene exposed on window.__nadocTest' }

      const meshes = []
      scene.traverse(obj => {
        if (obj.isMesh && obj.renderOrder === 100 &&
            obj.material?.type === 'MeshPhongMaterial' && obj.material?.transparent) {
          const pos = obj.geometry?.attributes?.position
          if (pos && pos.count > 0) meshes.push(obj)
        }
      })
      if (meshes.length === 0) {
        return { error: 'no hull meshes (renderOrder 100, transparent MeshPhong) found in scene' }
      }

      // Collect all vertices in WORLD space.
      const xs = [], ys = [], zs = []
      for (const m of meshes) {
        m.updateWorldMatrix(true, false)
        const pos = m.geometry.attributes.position
        const e = m.matrixWorld.elements
        for (let i = 0; i < pos.count; i++) {
          const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i)
          xs.push(e[0] * x + e[4] * y + e[8]  * z + e[12])
          ys.push(e[1] * x + e[5] * y + e[9]  * z + e[13])
          zs.push(e[2] * x + e[6] * y + e[10] * z + e[14])
        }
      }

      // Count contiguous bands along a sorted 1-D projection.
      function bandsAlong(vals) {
        const s = vals.slice().sort((a, b) => a - b)
        let bands = 1
        const ranges = [[s[0], s[0]]]
        for (let i = 1; i < s.length; i++) {
          if (s[i] - s[i - 1] > gapNm) {
            bands++
            ranges.push([s[i], s[i]])
          } else {
            ranges[ranges.length - 1][1] = s[i]
          }
        }
        return { bands, ranges: ranges.map(r => [Number(r[0].toFixed(2)), Number(r[1].toFixed(2))]) }
      }

      const ax = { x: bandsAlong(xs), y: bandsAlong(ys), z: bandsAlong(zs) }
      const maxBands = Math.max(ax.x.bands, ax.y.bands, ax.z.bands)

      return {
        meshCount: meshes.length,
        vertexCount: xs.length,
        perAxis: { x: ax.x, y: ax.y, z: ax.z },
        maxBands,
      }
    }, { gapNm: GAP_NM })

    // Screenshot for eyeballing (canvas only).
    await page.screenshot({ path: 'e2e/screenshots/hull_mini_hinge.png' })

    console.log('HULL_DISJOINT_RESULT', JSON.stringify(result))
    if (consoleErrors.length) console.log('PAGE_CONSOLE_ERRORS', JSON.stringify(consoleErrors))

    expect(result.error, result.error || '').toBeFalsy()
    // The two arms are separated along exactly one principal axis -> 2 disjoint
    // volumes there. No principal axis should show more than 2 (a single merged
    // continuous block would show 1 along every axis).
    expect(result.maxBands).toBe(2)
  })
})
