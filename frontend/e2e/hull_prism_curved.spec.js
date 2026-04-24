/**
 * Visual inspection of the curved hull prism for bent designs.
 *
 * Loads BS Nonsense/b3.nadoc, enables the hull-prism representation,
 * orbits the camera to the Y-plane view and ±15° perturbations to expose
 * the slanted end-cap artefact the user reported.
 */

import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'
import { join } from 'path'

const API      = 'http://localhost:8000/api'
const DESIGN   = join('/home/joshua/NADOC/workspace/BS Nonsense', 'b3.nadoc')
const OUT      = 'e2e/screenshots/hull_prism_curved'

// ── helpers ────────────────────────────────────────────────────────────────

async function loadDesign(page) {
  const content = readFileSync(DESIGN, 'utf-8')
  const resp = await page.request.post(`${API}/design/import`, {
    data: { content },
  })
  expect(resp.ok()).toBeTruthy()
  await page.goto('/')
  await page.waitForTimeout(2000)
}

async function enableHullPrism(page) {
  await page.evaluate(() => document.getElementById('menu-view-hull-prism').click())
  await page.waitForTimeout(800)
}

/**
 * Orbit via left-button drag on the canvas.
 * OrbitControls: dx maps to azimuth, dy maps to polar.
 * At 720px canvas height, 15° ≈ 60px  (π * dy / height).
 */
async function orbit(page, dx, dy) {
  const canvas = page.locator('#canvas')
  const box    = await canvas.boundingBox()
  const cx     = box.x + box.width  / 2
  const cy     = box.y + box.height / 2
  await page.mouse.move(cx, cy)
  await page.mouse.down({ button: 'left' })
  await page.mouse.move(cx + dx, cy + dy, { steps: 20 })
  await page.mouse.up({ button: 'left' })
  await page.waitForTimeout(300)
}

// ── tests ──────────────────────────────────────────────────────────────────

test.describe('Hull prism — curved design (b3.nadoc)', () => {
  test.setTimeout(120_000)

  test.beforeEach(async ({ page }) => {
    await loadDesign(page)
    await enableHullPrism(page)
  })

  /**
   * Y-plane view: orbit down 300px (~75°) from the default ISO so the camera
   * is roughly horizontal looking along the Z axis.  Then perturb ±15° in
   * both azimuth (+x/-x) and elevation (+y/-y) to expose the slanted-cap bug.
   */
  test('Y-plane view and ±15° perturbations', async ({ page }) => {
    // Pull the camera to a horizontal side view (cancel most of the default elevation).
    await orbit(page, -50, -300)
    await page.screenshot({ path: `${OUT}_yplane_0_base.png` })

    // +15° azimuth (tilt right)
    await orbit(page, 60, 0)
    await page.screenshot({ path: `${OUT}_yplane_1_az_plus.png` })

    // −30° azimuth (step back past base to −15°)
    await orbit(page, -120, 0)
    await page.screenshot({ path: `${OUT}_yplane_2_az_minus.png` })

    // Back to base azimuth, then +15° elevation (tilt up)
    await orbit(page, 60, 0)
    await orbit(page, 0, -60)
    await page.screenshot({ path: `${OUT}_yplane_3_el_plus.png` })

    // −30° elevation (step back past base to −15°)
    await orbit(page, 0, 120)
    await page.screenshot({ path: `${OUT}_yplane_4_el_minus.png` })
  })

  /**
   * End-on view at various fine increments to catch the slanted appearance
   * at whichever angle it appears.
   */
  test('end-on sweep', async ({ page }) => {
    // Orbit to look along the beam axis.
    await orbit(page, 200, 0)
    await page.screenshot({ path: `${OUT}_endon_0_straight.png` })

    for (let deg = 15; deg <= 60; deg += 15) {
      const px = Math.round(deg / 180 * 720)
      await orbit(page, 0, -px)
      await page.screenshot({ path: `${OUT}_endon_up${deg}.png` })
      await orbit(page, 0, px * 2)
      await page.screenshot({ path: `${OUT}_endon_dn${deg}.png` })
      await orbit(page, 0, -px)   // back to level
    }
  })

  test('hull mesh exists in scene for each cluster', async ({ page }) => {
    const hullCount = await page.evaluate(() => {
      let count = 0
      window.__nadocTest?.scene?.traverse(obj => {
        if (obj.isMesh && obj.renderOrder === 100 &&
            obj.material?.type === 'MeshPhongMaterial' && obj.material?.transparent) {
          count++
        }
      })
      return count
    })
    expect(hullCount).toBeGreaterThan(0)
  })
})
