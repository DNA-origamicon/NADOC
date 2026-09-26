import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DOC = '__e2e__active-atomistic-playback'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const ownedPaths = [`.session/${DOC}`, `.nadoc-projects/${DOC}`, `${DOC}.nadoc`]
  .map(path => `${ROOT}workspace/${path}`)
let content

test.beforeAll(() => {
  for (const path of ownedPaths) expect(existsSync(path), `Pre-existing test artifact: ${path}`).toBe(false)
  content = execFileSync('uv', ['run', 'python', '-c',
    `from tests.conftest import make_6hb_design; d=make_6hb_design(21); d.id='${DOC}'; d.metadata.name='${DOC}'; print(d.model_dump_json())`],
  { cwd: ROOT, encoding: 'utf8' })
})

test.afterEach(async ({ page, request }) => {
  try {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${DOC}`)
  } finally {
    for (const path of ownedPaths) rmSync(path, { recursive: true, force: true })
    for (const path of ownedPaths) expect(existsSync(path)).toBe(false)
  }
})

test('real bundle retains pixels, picking, colours and buffers during atomistic frame updates', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', msg => { if (msg.type() === 'error' && /WebGL|shader/i.test(msg.text())) errors.push(msg.text()) })
  await page.goto(`/?doc=${DOC}`)
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, content)
  const responsePromise = page.waitForResponse(r => /\/api\/design\/atomistic\?/.test(r.url()) && r.status() === 200)
  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  const model = await (await responsePromise).json()
  expect(model.atoms.length).toBeGreaterThan(100)
  await expect.poll(() => page.evaluate(() => {
    let count = 0
    window.__nadocTest.getAtomisticRenderer().visitAtoms(() => count++)
    return count
  }), { timeout: 60000 }).toBe(model.atoms.length)
  const result = await page.evaluate(async model => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const t = window.__nadocTest, ar = t.getAtomisticRenderer()
    t.pauseViewerRenderingForTest()
    ar.update({ ...model, sphereImpostors: true })
    ar.setUniformOpacity(.7)
    const atomMeshes = () => t.scene.children.filter(m => m.isInstancedMesh && /^(atomSpheres|atomBonds)$/.test(m.name))
    const meshes = atomMeshes()
    const maxSerial = Math.max(...model.atoms.map(a => a.serial))
    const from = new Float64Array((maxSerial + 1) * 3), to = from.slice()
    const box = new THREE.Box3()
    for (const a of model.atoms) {
      from.set([a.x, a.y, a.z], a.serial * 3)
      to.set([a.x + .4, a.y - .2, a.z + .1], a.serial * 3)
      box.expandByPoint(new THREE.Vector3(a.x, a.y, a.z))
    }
    const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length()
    t.applyCameraPoseForTest({ position: [center.x, center.y, center.z + size * 1.5], target: center.toArray() })
    const alphaBefore = meshes.map(m => Array.from(m.geometry.getAttribute('instanceAlpha')?.array ?? []))
    const colorBefore = meshes.map(m => Array.from(m.instanceColor?.array ?? []))
    const expected = Float64Array.from(from, (v, i) => v + (to[i] - v) * .37)
    ar.applyPositionLerp(from, to, .37)
    const interpolated = meshes.map(m => m.instanceMatrix.array.slice())
    const imageA = t.renderedPixelCensus()
    const first = model.atoms[0], s = first.serial * 3
    const ray = new THREE.Raycaster(new THREE.Vector3(expected[s], expected[s+1], expected[s+2]+20), new THREE.Vector3(0,0,-1))
    t.scene.updateMatrixWorld(true)
    const pickA = ar.raycastPick(ray)?.atom.serial
    ar.applyPositionLerp(expected, expected, 0)
    const imageB = t.renderedPixelCensus()
    t.scene.updateMatrixWorld(true)
    const pickB = ar.raycastPick(ray)?.atom.serial
    const snapshotMatches = meshes.every((m, j) => m.instanceMatrix.array.every((v, i) => v === interpolated[j][i]))
    const next = { ...model, atoms: model.atoms.map(a => ({ ...a,
      x: expected[a.serial*3], y: expected[a.serial*3+1], z: expected[a.serial*3+2] })), sphereImpostors: true }
    const updateKind = ar.updateFrame(next)
    const imageC = t.renderedPixelCensus()
    const colorsStable = meshes.every((m, j) => (m.instanceColor?.array ?? []).every((v, i) => v === colorBefore[j][i]))
    const alphaStable = meshes.every((m, j) => (m.geometry.getAttribute('instanceAlpha')?.array ?? []).every((v, i) => v === alphaBefore[j][i]))
    return { atoms: model.atoms.length, meshes: meshes.length, updateKind, snapshotMatches,
      sameMeshes: atomMeshes().every((m, i) => m === meshes[i]), colorsStable, alphaStable,
      pickA, pickB, imageA, imageB, imageC }
  }, model)
  expect(result.meshes).toBeGreaterThan(1)
  expect(result.snapshotMatches).toBe(true)
  expect(result.updateKind).toBe('coordinates')
  expect(result.sameMeshes && result.colorsStable && result.alphaStable).toBe(true)
  expect(result.pickA).toBeDefined()
  expect(result.pickA).toBe(result.pickB)
  expect(result.imageA.visible).toBeGreaterThan(100)
  expect(result.imageA.pixelHash).toBe(result.imageB.pixelHash)
  expect(result.imageA.pixelHash).toBe(result.imageC.pixelHash)
  expect(errors).toEqual([])
  console.log('active atomistic verification', JSON.stringify(result))
})
