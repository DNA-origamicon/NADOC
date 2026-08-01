/**
 * Sphere-impostor backbone beads — Phase A verification (design/part editor).
 *
 * Builds a small scaffold-bearing part (so there are backbone beads) with the
 * impostor flag on (`?impostors=1`) and confirms:
 *   1. the backbone-bead InstancedMesh is an impostor (quad geometry, 4 verts,
 *      material.userData.isImpostor) with a real instance count,
 *   2. no shader-compile / WebGLProgram errors hit the console (the shader
 *      actually links — the main correctness risk for a custom onBeforeCompile),
 *   3. a screenshot for visual confirmation the beads paint as round lit spheres.
 *
 * Picking / physics / deform / unfold are exercised as a manual USER TODO.
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000/api'

/** New Part via the File menu, then build a single scaffolded helix via the API
 *  (same backend session). Mirrors atomistic_helix_parity.spec.js. */
async function buildScaffoldedPart(page, name) {
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#splash-screen')).not.toBeVisible({ timeout: 10_000 })
  await page.waitForTimeout(500)

  await page.request.post(`${API}/design/helix-at-cell`, {
    data: { row: 0, col: 0, length_bp: 200 },
    headers: { 'Content-Type': 'application/json' },
  })
  // Scaffold by painting a domain over the full helix. (Was a POST to
  // /design/auto-scaffold with this as a fallback; e9d6750 removed that route in
  // favour of -seamed/-seamless, so the fallback is what has always run.)
  const dr = await page.request.get(`${API}/design`)
  const { design } = await dr.json()
  const h = design.helices[0]
  await page.request.post(`${API}/design/scaffold-domain-paint`, {
    data: { helix_id: h.id, lo_bp: 0, hi_bp: 199 },
    headers: { 'Content-Type': 'application/json' },
  })
  // page.request mutations bypass the frontend's API client, so nudge the app
  // to re-fetch the active design via the same BroadcastChannel the cadnano
  // editor uses ('nadoc-design' → main.js design-changed handler → getDesign +
  // getGeometry → rebuild).
  await page.evaluate(() => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed' })
    bc.close()
  })
  // Poll until the design has actually rebuilt (a fixed wait was flaky under a
  // busy dev server — the rebuild can land well after 2.5 s).
  await page.waitForFunction(() => {
    const scene = window.__nadocTest?.scene
    if (!scene) return false
    let ok = false
    scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 20_000 })
  await page.waitForTimeout(300)   // settle one more frame for LOD/visibility
}

function inspectBeadMesh() {
  const scene = window.__nadocTest?.scene
  if (!scene) return { err: 'no __nadocTest.scene' }
  let mesh = null
  scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres') mesh = o })
  if (!mesh) return { err: 'no backboneSpheres mesh' }
  const posAttr = mesh.geometry.getAttribute('position')
  return {
    count: mesh.count,
    vertexCount: posAttr ? posAttr.count : -1,
    isImpostor: !!mesh.material?.userData?.isImpostor,
    impostorRadius: mesh.material?.userData?.impostorRadius ?? null,
    visible: mesh.visible,
    // own-property raycast = the ray-vs-sphere override is installed (the
    // default InstancedMesh.raycast lives on the prototype).
    hasCustomRaycast: Object.prototype.hasOwnProperty.call(mesh, 'raycast'),
  }
}

test.describe('Sphere impostors — Phase A (design view)', () => {

  test('backbone beads render as impostors with no shader errors', async ({ page }) => {
    const errors = []
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', e => errors.push(String(e)))

    await page.goto('/?impostors=1')
    await buildScaffoldedPart(page, 'impostor-on')

    const info = await page.evaluate(inspectBeadMesh)
    expect(info.err, info.err).toBeUndefined()
    expect(info.isImpostor).toBe(true)
    expect(info.vertexCount).toBe(4)            // PlaneGeometry(2,2) quad
    expect(info.impostorRadius).toBeCloseTo(0.10, 5)
    expect(info.visible).toBe(true)
    expect(info.count).toBeGreaterThan(50)
    expect(info.hasCustomRaycast).toBe(true)   // ray-vs-sphere picking override installed

    await page.screenshot({ path: 'e2e/screenshots/impostor_beads.png', fullPage: true })

    // Close-up: zoom in on the structure so the bead shading gradient is visible
    // (confirms the impostor paints a LIT sphere, not a flat disc).
    const box = await page.locator('#canvas').boundingBox()
    const cx = box.x + box.width * 0.20, cy = box.y + box.height * 0.72
    await page.mouse.move(cx, cy)
    for (let i = 0; i < 12; i++) await page.mouse.wheel(0, -120)
    await page.waitForTimeout(800)
    await page.screenshot({ path: 'e2e/screenshots/impostor_beads_closeup.png', fullPage: true })

    const shaderErrors = errors.filter(t =>
      /Shader Error|WebGLProgram|getProgramInfoLog|VALIDATE_STATUS|getShaderInfoLog/i.test(t))
    expect(shaderErrors, shaderErrors.join('\n')).toHaveLength(0)
  })

  test('real design (teeth.nadoc) renders impostor beads with no shader errors', async ({ page }) => {
    const errors = []
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', e => errors.push(String(e)))

    await page.goto('/?impostors=1')
    await page.waitForSelector('#canvas')
    // Enter the editor via New Part (dismisses launcher), then swap the active
    // design to the saved teeth.nadoc and nudge a rebuild.
    const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
    await fileMenu.hover()
    await page.click('#menu-file-new')
    await page.fill('#new-design-name', 'tmp')
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.locator('#splash-screen')).not.toBeVisible({ timeout: 10_000 })

    const r = await page.request.post(`${API}/design/load`, {
      data: { path: '/home/joshua/NADOC/workspace/teeth.nadoc' },
      headers: { 'Content-Type': 'application/json' },
    })
    expect(r.ok(), `load teeth.nadoc → ${r.status()}`).toBeTruthy()
    await page.evaluate(() => {
      const bc = new BroadcastChannel('nadoc-design')
      bc.postMessage({ type: 'design-changed' }); bc.close()
    })
    const built = await page.waitForFunction(() => {
      const scene = window.__nadocTest?.scene
      if (!scene) return false
      let ok = false
      scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
      return ok
    }, null, { timeout: 12_000 }).catch(() => null)
    await page.waitForTimeout(400)
    await page.screenshot({ path: 'e2e/screenshots/impostor_teeth.png', fullPage: true })
    expect(built, 'teeth.nadoc never produced a populated backboneSpheres mesh').not.toBeNull()

    const info = await page.evaluate(inspectBeadMesh)
    expect(info.err, info.err).toBeUndefined()
    expect(info.isImpostor).toBe(true)
    expect(info.vertexCount).toBe(4)
    expect(info.count).toBeGreaterThan(500)   // teeth.nadoc is a large multi-helix design

    const shaderErrors = errors.filter(t =>
      /Shader Error|WebGLProgram|getProgramInfoLog|VALIDATE_STATUS|getShaderInfoLog/i.test(t))
    expect(shaderErrors, shaderErrors.join('\n')).toHaveLength(0)
  })

  test('flag off keeps real sphere geometry (baseline unchanged)', async ({ page }) => {
    await page.goto('/')   // no flag
    await buildScaffoldedPart(page, 'impostor-off')

    const info = await page.evaluate(inspectBeadMesh)
    expect(info.err, info.err).toBeUndefined()
    expect(info.isImpostor).toBe(false)
    expect(info.vertexCount).toBeGreaterThan(4)   // real SphereGeometry
  })
})
