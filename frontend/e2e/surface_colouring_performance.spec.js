import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DOC = '__e2e__surface-colouring'
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

test('original and optimized simulation renderers produce identical pixels on a real bundle', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', msg => { if (msg.type() === 'error' && /WebGL|shader/i.test(msg.text())) errors.push(msg.text()) })
  // Read-only baseline served from memory: no generated source files in the repo.
  const revision = '0dc8b857378b077a739289f413a23cfad3e234a3'
  for (const name of ['atomistic_renderer', 'surface_renderer']) {
    const body = execFileSync('git', ['show', `${revision}:frontend/src/scene/${name}.js`], { cwd: ROOT, encoding: 'utf8' }).replace(/from ['"]three['"]/g, "from '/node_modules/three/build/three.module.js'")
    await page.route(`**/src/scene/__original_${name}.js`, route => route.fulfill({ contentType: 'text/javascript', body }))
  }
  await page.goto(`/?doc=${DOC}`)
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, content)
  const response = page.waitForResponse(r => /\/api\/design\/atomistic\?/.test(r.url()) && r.status() === 200)
  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  const model = await (await response).json()
  await expect.poll(() => page.evaluate(() => {
    let count = 0; window.__nadocTest.getAtomisticRenderer().visitAtoms(() => count++); return count
  }), { timeout: 60000 }).toBe(model.atoms.length)
  const result = await page.evaluate(async model => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const oldAtom = await import('/src/scene/__original_atomistic_renderer.js')
    const newAtom = await import('/src/scene/atomistic_renderer.js')
    const oldSurface = await import('/src/scene/__original_surface_renderer.js')
    const newSurface = await import('/src/scene/surface_renderer.js')
    const api = await import('/src/api/client.js')
    const { parseSurfaceBin } = await import('/src/scene/surface_bin.js')
    const data = parseSurfaceBin(await api.getDesignSurfaceBin())
    if (!data?.vertices.length) throw new Error('No real molecular surface returned')
    const t = window.__nadocTest
    t.pauseViewerRenderingForTest()
    t.getAtomisticRenderer().setMode('off')
    const box = new THREE.Box3()
    for (const a of model.atoms) box.expandByPoint(new THREE.Vector3(a.x, a.y, a.z))
    const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length()
    t.applyCameraPoseForTest({ position: [center.x, center.y, center.z + size * 1.5], target: center.toArray() })
    const key = a => `${a.helix_id}:${a.bp_index}:${a.direction}`
    const checks = []
    for (const impostors of [false, true]) {
      const paired = []
      for (const init of [oldAtom.initAtomisticRenderer, newAtom.initAtomisticRenderer]) {
        const r = init(t.scene, { independentColors: true })
        r.setMode('ballstick'); r.update({ ...model, sphereImpostors: impostors })
        const colors = new Map(model.atoms.map((a, i) => [key(a), i % 3 ? 0x376abc : 0xd13478]))
        const alphas = new Map(model.atoms.map((a, i) => [key(a), i % 3 ? .4 : 1]))
        const images = []
        const capture = () => images.push(t.renderedPixelCensus())
        r.setClusterDisplay(alphas, colors); capture()
        r.highlight({ strandIds: [model.atoms[0].strand_id] }); capture()
        r.applyScalarColors(new Map([...colors.keys()].map(k => [k, 0x7fba23]))); capture()
        r.highlight(null); capture()
        colors.set(key(model.atoms[0]), 0xff0000); alphas.set(key(model.atoms[0]), .1)
        r.clearScalarColors(); r.setClusterDisplay(alphas, colors); capture()
        r.setClusterDisplay(new Map(), new Map()); capture()
        t.scene.updateMatrixWorld(true)
        const a = model.atoms[0]
        const ray = new THREE.Raycaster(new THREE.Vector3(a.x, a.y, a.z + 20), new THREE.Vector3(0, 0, -1))
        paired.push({ images, pick: r.raycastPick(ray)?.atom.serial })
        r.dispose()
      }
      checks.push({ mode: impostors ? 'impostors' : 'spheres', paired })
    }
    for (const photo of [false, true]) {
      const paired = []
      for (const init of [oldSurface.initSurfaceRenderer, newSurface.initSurfaceRenderer]) {
        const frame = structuredClone(data)
        frame.scalar = true
        const r = init(t.scene); r.update(frame)
        if (photo) {
          r.getMesh().material.dispose()
          r.getMesh().material = new THREE.MeshPhysicalMaterial({ color: 0xffffff,
            vertexColors: true, transparent: true, opacity: .85, roughness: .4, side: THREE.DoubleSide })
        }
        const images = []
        r.applyClusterDisplay({ strandAlphas: new Map(frame.vertex_strand_index_table.map((s, i) => [s, i % 2 ? .4 : 1])),
          nucAlphas: new Map((frame.vertex_nuc_index_table ?? []).map((s, i) => [s, i % 2 ? .4 : 1])) })
        for (let k = 0; k < 3; k++) {
          if (k === 1) frame.vertex_colors[0] = .1234
          if (k === 2) frame.vertices[2] += .01
          r.applyPositionLerp(frame, frame, 0)
          images.push(t.renderedPixelCensus())
        }
        t.scene.updateMatrixWorld(true)
        // Aim at an actual triangle; the bundle centre can fall in its pore.
        const geo = r.getMesh().geometry
        const corners = [0, 1, 2].map(i => new THREE.Vector3().fromBufferAttribute(geo.attributes.position, geo.index.array[i]))
        const target = corners[0].clone().add(corners[1]).add(corners[2]).multiplyScalar(1 / 3)
        const normal = corners[1].clone().sub(corners[0]).cross(corners[2].clone().sub(corners[0])).normalize()
        const ray = new THREE.Raycaster(target.clone().addScaledVector(normal, size * 2), normal.negate())
        const hit = ray.intersectObject(r.getMesh())[0]
        paired.push({ images, pick: hit ? r.strandIdAt(hit.face) : null })
        r.dispose()
      }
      checks.push({ mode: photo ? 'surface_physical' : 'surface_phong', paired })
    }
    return { atoms: model.atoms.length, vertices: data.vertices.length / 3, faces: data.faces.length / 3, checks }
  }, model)
  for (const { mode, paired } of result.checks) {
    expect(paired[0].pick, mode).toBeDefined()
    expect(paired[0].pick, mode).not.toBeNull()
    expect(paired[1].pick, mode).toEqual(paired[0].pick)
    for (let i = 0; i < paired[0].images.length; i++) {
      expect(paired[0].images[i].visible, mode).toBeGreaterThan(100)
      expect(paired[1].images[i].pixelHash, `${mode} state ${i}`).toBe(paired[0].images[i].pixelHash)
    }
  }
  expect(errors).toEqual([])
  console.log('surface colouring verification', JSON.stringify(result))
})
