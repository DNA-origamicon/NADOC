/**
 * Hull prism diagnostic for Nanosynth_Final.nadoc.
 *
 * Loads the design, enables hull-prism repr, captures screenshots from several
 * angles, and logs hull mesh bounding-box data for each cluster to verify the
 * hulls are sized/positioned correctly.
 */

import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'

const API    = 'http://localhost:8000/api'
const DESIGN = '/home/joshua/NADOC/workspace/Nanosynth_Final.nadoc'
const OUT    = 'e2e/screenshots/hull_nanosynth'

// ── helpers ────────────────────────────────────────────────────────────────

async function loadDesign(page) {
  const content = readFileSync(DESIGN, 'utf-8')
  const resp = await page.request.post(`${API}/design/import`, {
    data: { content },
  })
  expect(resp.ok()).toBeTruthy()
  await page.goto('/')
  await page.waitForTimeout(3000)
}

async function enableHullPrism(page) {
  await page.evaluate(() => document.getElementById('menu-view-hull-prism').click())
  await page.waitForTimeout(1200)
}

async function orbit(page, dx, dy) {
  const canvas = page.locator('#canvas')
  const box    = await canvas.boundingBox()
  const cx     = box.x + box.width  / 2
  const cy     = box.y + box.height / 2
  await page.mouse.move(cx, cy)
  await page.mouse.down({ button: 'left' })
  await page.mouse.move(cx + dx, cy + dy, { steps: 20 })
  await page.mouse.up({ button: 'left' })
  await page.waitForTimeout(400)
}

/**
 * Collect bounding-box data for every hull mesh (renderOrder=100, transparent
 * MeshPhongMaterial) in the scene.  Returns array of { min, max, center, size }.
 */
async function getHullMeshStats(page) {
  return page.evaluate(() => {
    const THREE = window.__nadocTest?.scene?.constructor
      ? (window._threeRef ?? null) : null

    const meshes = []
    window.__nadocTest?.scene?.traverse(obj => {
      if (obj.isMesh && obj.renderOrder === 100 &&
          obj.material && obj.material.type === 'MeshPhongMaterial' && obj.material.transparent) {
        // Compute bounding box in world space
        const geo = obj.geometry
        if (!geo.boundingBox) geo.computeBoundingBox()
        const bb = geo.boundingBox.clone().applyMatrix4(obj.matrixWorld)
        meshes.push({
          opacity:  obj.material.opacity,
          position: { x: obj.position.x, y: obj.position.y, z: obj.position.z },
          min: { x: bb.min.x, y: bb.min.y, z: bb.min.z },
          max: { x: bb.max.x, y: bb.max.y, z: bb.max.z },
          center: {
            x: (bb.min.x + bb.max.x) / 2,
            y: (bb.min.y + bb.max.y) / 2,
            z: (bb.min.z + bb.max.z) / 2,
          },
          size: {
            x: bb.max.x - bb.min.x,
            y: bb.max.y - bb.min.y,
            z: bb.max.z - bb.min.z,
          },
        })
      }
    })
    return meshes
  })
}

/**
 * Get backbone point stats per cluster from the store geometry —
 * shows which backbone points feed into each cluster hull.
 */
async function getClusterBackboneStats(page) {
  return page.evaluate(() => {
    // Access the store via the exposed scene traversal (store is module-scoped)
    // Instead, pull data from the API response already in the page.
    // We rely on window.__nadocStoreSnapshot if exposed, else return null.
    return window.__nadocStoreSnapshot ?? null
  })
}

// ── expose store snapshot helper so we can read it from tests ──────────────
async function exposeStoreSnapshot(page) {
  await page.evaluate(() => {
    // Walk all module instances to find the store — look for it on jointRenderer
    // via window globals. Actually intercept via scene userData.
    // Simpler: the design and geometry are available from the API.
    return null
  })
}

// ── tests ──────────────────────────────────────────────────────────────────

test.describe('Hull prism — Nanosynth_Final.nadoc', () => {
  test.setTimeout(120_000)

  test.beforeEach(async ({ page }) => {
    await loadDesign(page)
    await enableHullPrism(page)
  })

  test('default ISO view', async ({ page }) => {
    await page.screenshot({ path: `${OUT}_1_default.png` })
  })

  test('side view (looking along X)', async ({ page }) => {
    // Orbit to look along X — rotate azimuth 90° right
    await orbit(page, 280, 0)
    await page.screenshot({ path: `${OUT}_2_side_x.png` })
  })

  test('end-on view (looking along Z)', async ({ page }) => {
    // Pull down to horizontal then look along Z
    await orbit(page, 0, -280)
    await page.screenshot({ path: `${OUT}_3_end_on.png` })
  })

  test('top-down view', async ({ page }) => {
    // Orbit up to near-top view
    await orbit(page, 0, 280)
    await page.screenshot({ path: `${OUT}_4_top.png` })
  })

  test('XY cross-section view (looking along Z bundle axis)', async ({ page }) => {
    // Orbit to look roughly along the Z axis: from default ISO, orbit up ~75°
    // so camera is nearly at the +Z end looking back along -Z.
    // A large dy (≈300px ≈ 75° assuming 720px → 180°) lifts the camera overhead;
    // combining with dx=-200 sweeps azimuth to put us more end-on.
    await orbit(page, -200, 300)
    await page.screenshot({ path: `${OUT}_5_along_z.png` })
  })

  test('Y-axis cross-section (looking from below, -Y direction)', async ({ page }) => {
    // Orbit so the camera is roughly underneath, looking up at the -Y face.
    // Start from default ISO, orbit dy=-300 to tilt camera downward.
    await orbit(page, 0, -300)
    await page.screenshot({ path: `${OUT}_6_from_below.png` })
  })

  test('hull mesh bounding boxes', async ({ page }) => {
    const stats = await getHullMeshStats(page)
    console.log('\n=== Hull mesh bounding boxes ===')
    for (const [i, m] of stats.entries()) {
      console.log(`Mesh ${i}: opacity=${m.opacity.toFixed(2)}`)
      console.log(`  position: (${m.position.x.toFixed(2)}, ${m.position.y.toFixed(2)}, ${m.position.z.toFixed(2)})`)
      console.log(`  world min: (${m.min.x.toFixed(2)}, ${m.min.y.toFixed(2)}, ${m.min.z.toFixed(2)})`)
      console.log(`  world max: (${m.max.x.toFixed(2)}, ${m.max.y.toFixed(2)}, ${m.max.z.toFixed(2)})`)
      console.log(`  center:   (${m.center.x.toFixed(2)}, ${m.center.y.toFixed(2)}, ${m.center.z.toFixed(2)})`)
      console.log(`  size:     (${m.size.x.toFixed(2)}, ${m.size.y.toFixed(2)}, ${m.size.z.toFixed(2)})`)
    }
    expect(stats.length).toBeGreaterThan(0)
  })

  test('geometry and design accessible from API', async ({ page }) => {
    // Pull geometry from the backend to understand what backbone positions
    // the hull renderer would have available.
    const designResp = await page.request.get(`${API}/design`)
    expect(designResp.ok()).toBeTruthy()
    const { design } = await designResp.json()

    const clusters = design?.cluster_transforms ?? []
    console.log(`\n=== Clusters (${clusters.length}) ===`)
    for (const c of clusters) {
      console.log(`  ${c.name} (${c.id}): ${c.helix_ids.length} helices, translation=${JSON.stringify(c.translation)}`)
    }

    const geoResp = await page.request.get(`${API}/design/geometry`)
    expect(geoResp.ok()).toBeTruthy()
    const geoData = await geoResp.json()
    const geometry = geoData?.nucleotides ?? geoData ?? []
    console.log(`\n=== Geometry: ${geometry.length} nucleotide positions ===`)

    for (const cluster of clusters) {
      const helixSet = new Set(cluster.helix_ids)

      // Count dsDNA positions (both directions present, no overhang)
      const dsCount = new Map()
      for (const nuc of geometry) {
        if (!helixSet.has(nuc.helix_id) || !nuc.strand_id || nuc.overhang_id) continue
        const k = `${nuc.helix_id}:${nuc.bp_index}`
        dsCount.set(k, (dsCount.get(k) ?? 0) + 1)
      }
      const dsPositions = [...dsCount.entries()].filter(([, v]) => v >= 2).length
      const ssPositions = [...dsCount.entries()].filter(([, v]) => v < 2).length
      const ovhPositions = geometry.filter(n => helixSet.has(n.helix_id) && n.overhang_id).length

      // Collect dsDNA backbone points to compute actual extents
      const pts = []
      for (const nuc of geometry) {
        if (!helixSet.has(nuc.helix_id) || !nuc.strand_id || nuc.overhang_id) continue
        if ((dsCount.get(`${nuc.helix_id}:${nuc.bp_index}`) ?? 0) >= 2) {
          pts.push(nuc.backbone_position)
        }
      }

      let minY = Infinity, maxY = -Infinity
      let minZ = Infinity, maxZ = -Infinity
      for (const [x, y, z] of pts) {
        if (y < minY) minY = y; if (y > maxY) maxY = y
        if (z < minZ) minZ = z; if (z > maxZ) maxZ = z
      }

      console.log(`\n  Cluster "${cluster.name}":`)
      console.log(`    dsDNA positions: ${dsPositions}, ssDNA: ${ssPositions}, overhang: ${ovhPositions}`)
      console.log(`    dsDNA backbone pts used for hull: ${pts.length}`)
      if (pts.length) {
        console.log(`    Y range: ${minY.toFixed(2)} – ${maxY.toFixed(2)}`)
        console.log(`    Z range: ${minZ.toFixed(2)} – ${maxZ.toFixed(2)}`)
      }
    }
  })
})
