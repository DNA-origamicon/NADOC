/**
 * Photomode — ChimeraX-style silhouette outline.
 *
 * The silhouette is a GLSL branch, so vitest can only pin the JS→uniform
 * plumbing. Everything that can actually go wrong lives in the shader:
 *   • it has to COMPILE (a stray backtick or a non-constant loop bound in the
 *     disc min-filter is a silent black screen, not a test failure),
 *   • the branch has to be REACHED (uSilhouette wired all the way through),
 *   • depth_jump has to move the contour count. Note this can ONLY be measured
 *     on INTERNAL contours (helix occluding helix): the outer silhouette runs
 *     against background depth, which is clamped to the far plane, so it clears
 *     every threshold and is jump-independent by construction.
 *
 * Run:  npx playwright test e2e/photo_silhouette.spec.js
 */

import { test, expect } from '@playwright/test'

// The design is opened THROUGH THE UI (welcome-screen file browser) rather than
// by POSTing /design/load: the app only adopts the backend's active design when
// it opens one itself, and the whole run stays on the config's throwaway backend
// (:8002) — never the user's dev server.
const DESIGN = '18hb'

/** Open a real multi-helix bundle so there are INTERNAL depth discontinuities. */
async function loadDesign(page) {
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.locator('.lib-search-input').first().fill(DESIGN)
  await page.waitForTimeout(800)
  await page.locator('.lib-file-row', { has: page.locator(`.lib-row-name:text-is("${DESIGN}")`) })
    .first().click()
  await page.waitForFunction(() => {
    const scene = window.__nadocTest?.scene
    if (!scene) return false
    let ok = false
    scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 30_000 })
  await page.waitForTimeout(1000)
}

/**
 * Count near-black pixels in the viewport — the outline colour is #1b1f24
 * against the white sky we set below.
 *
 * The pixels come from a Playwright screenshot, NOT `canvas.toBlob`: the WebGL
 * context has preserveDrawingBuffer:false, so toBlob hangs forever outside the
 * render callback. Playwright reads the compositor instead. `page.screenshot`
 * with an explicit clip, not `locator.screenshot` — on software GL the latter's
 * stability wait never settles (see memory/project_photo_mode.md).
 */
async function darkPixelCount(page) {
  const box = await page.locator('#canvas').boundingBox()
  const png = await page.screenshot({ clip: box })
  return page.evaluate(async b64 => {
    const bmp = await createImageBitmap(await (await fetch(`data:image/png;base64,${b64}`)).blob())
    const c = new OffscreenCanvas(bmp.width, bmp.height)
    const ctx = c.getContext('2d')
    ctx.drawImage(bmp, 0, 0)
    const { data } = ctx.getImageData(0, 0, bmp.width, bmp.height)
    let n = 0
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] < 70 && data[i + 1] < 70 && data[i + 2] < 70) n++
    }
    return n
  }, png.toString('base64'))
}

test.describe('Photomode silhouette', () => {
  // Loading a real bundle and settling four render passes on software GL is slow;
  // the 30 s default is nowhere near enough.
  test.setTimeout(900_000)

  test('the ChimeraX depth-outline compiles, draws, and responds to depth_jump', async ({ page }) => {
    const errors = []
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', e => errors.push(String(e)))

    await loadDesign(page)

    await page.locator('#photo-tab-btn').click()
    await expect(page.locator('#tab-content-photo')).toBeVisible({ timeout: 5_000 })

    // White sky so "outline pixel" == "dark pixel".
    await page.locator('#photo-bg-color').fill('#ffffff')
    await page.locator('#photo-bg-color').dispatchEvent('input')
    await page.waitForTimeout(1500)

    const noOutline = await darkPixelCount(page)

    await page.locator('#photo-outline').check()
    await page.waitForTimeout(1200)
    const withOutline = await darkPixelCount(page)

    // A shader that failed to compile renders nothing / unchanged.
    expect(withOutline, `no outline=${noOutline} with outline=${withOutline}`)
      .toBeGreaterThan(noOutline)

    // depth_jump is a threshold: raising it must draw FEWER internal contours.
    // This is the assertion that proves the branch is reached AND that the
    // scene-depth span reached the uniform (with span 0 the threshold collapses
    // to far-near and the slider stops doing anything visible).
    const jump = page.locator('#photo-outline-jump')
    await jump.fill('0.005')
    await jump.dispatchEvent('input')
    await page.waitForTimeout(1200)
    const looseJump = await darkPixelCount(page)

    await jump.fill('0.15')
    await jump.dispatchEvent('input')
    await page.waitForTimeout(1200)
    const tightJump = await darkPixelCount(page)

    expect(looseJump, `jump 0.005=${looseJump}  jump 0.15=${tightJump}`)
      .toBeGreaterThan(tightJump)

    const shaderErrors = errors.filter(e => /shader|glsl|WebGLProgram/i.test(e))
    expect(shaderErrors, shaderErrors.join('\n')).toHaveLength(0)
  })

  test('the grid does not contaminate the silhouette', async ({ page }) => {
    // `scene.overrideMaterial` applies to Lines too, so a visible GridHelper used
    // to write depth into the figure pre-pass — stamping a contour along every
    // grid line and cutting spurious depth steps into the structure behind it.
    // Toggling the grid must now change NOTHING about the outline.
    await loadDesign(page)

    await page.locator('#photo-tab-btn').click()
    await expect(page.locator('#tab-content-photo')).toBeVisible({ timeout: 5_000 })
    await page.locator('#photo-bg-color').fill('#ffffff')
    await page.locator('#photo-bg-color').dispatchEvent('input')
    await page.locator('#photo-outline').check()
    await page.waitForTimeout(1500)

    const gridOff = await darkPixelCount(page)

    const shown = await page.evaluate(() => {
      let g = null
      window.__nadocTest.scene.traverse(o => { if (o.type === 'GridHelper') g = o })
      if (!g) return false
      g.visible = true
      return true
    })
    expect(shown, 'GridHelper must exist in the scene').toBe(true)
    await page.waitForTimeout(1500)
    const gridOn = await darkPixelCount(page)

    // The grid itself is drawn in the beauty pass (thin, light lines on white),
    // so allow a small delta — what must NOT happen is the outline colour being
    // stamped along every grid line, which was a large, obvious jump.
    const delta = Math.abs(gridOn - gridOff) / Math.max(gridOff, 1)
    expect(delta, `grid off=${gridOff} on=${gridOn} (${(delta * 100).toFixed(1)}%)`)
      .toBeLessThan(0.15)
  })
})
