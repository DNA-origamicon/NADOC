import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, rmSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DOC = '__e2e__loading-open'
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

test('first-open and compact scrubbing preserve pixels and picking while avoiding redundant GPU uploads', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', msg => { if (msg.type() === 'error' && /WebGL|shader/i.test(msg.text())) errors.push(msg.text()) })
  for (const name of ['atomistic_renderer', 'trajectory_stream']) {
    const body = readFileSync(`${ROOT}docs/audits/loading_open_20260926/baseline_${name}.js.txt`, 'utf8')
      .replace(/from ['"]three['"]/g, "from '/node_modules/three/build/three.module.js'")
    await page.route(`**/src/scene/__original_${name}.js`, route => route.fulfill({ contentType: 'text/javascript', body }))
  }
  await page.addInitScript(() => {
    window.__uploadAudit = { calls: 0, bytes: 0, dynamicBuffers: 0 }
    const proto = WebGL2RenderingContext.prototype
    const sub = proto.bufferSubData, data = proto.bufferData
    proto.bufferSubData = function(...args) {
      const a = window.__uploadAudit
      const source = args[2]
      if (!a.tracked || a.tracked.has(source)) {
        a.calls++
        a.bytes += args[4] ? args[4] * source.BYTES_PER_ELEMENT : source.byteLength
      }
      return sub.apply(this, args)
    }
    proto.bufferData = function(...args) {
      if (args[2] === this.DYNAMIC_DRAW) window.__uploadAudit.dynamicBuffers++
      return data.apply(this, args)
    }
  })
  await page.goto(`/?doc=${DOC}`)
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js'); await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, content)
  const response = page.waitForResponse(r => /\/api\/design\/atomistic\?/.test(r.url()) && r.status() === 200)
  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  const model = await (await response).json()
  await expect.poll(() => page.evaluate(() => {
    let n = 0; window.__nadocTest.getAtomisticRenderer().visitAtoms(() => n++); return n
  }), { timeout: 60000 }).toBe(model.atoms.length)
  const result = await page.evaluate(async model => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const before = await import('/src/scene/__original_atomistic_renderer.js')
    const after = await import('/src/scene/atomistic_renderer.js')
    const oldQueue = await import('/src/scene/__original_trajectory_stream.js')
    const newQueue = await import('/src/scene/trajectory_stream.js')
    const { expandMdAtomFrame } = await import('/src/scene/md_atom_frames_bin.js')
    const t = window.__nadocTest
    t.pauseViewerRenderingForTest(); t.getAtomisticRenderer().setMode('off')
    const sparse = { atoms: model.atoms.map(a => ({ ...a, serial: a.serial * 8 + 3 })),
      bonds: model.bonds.map(pair => pair.map(serial => serial * 8 + 3)) }
    const order = [...sparse.atoms].reverse()
    const frame = { serialMap: Uint32Array.from(order, a => a.serial),
      dense: Float64Array.from(order.flatMap(a => [a.x + .2, a.y - .1, a.z + .1])),
      length: (Math.max(...sparse.atoms.map(a => a.serial)) + 1) * 3 }
    const box = new THREE.Box3()
    for (const a of model.atoms) box.expandByPoint(new THREE.Vector3(a.x, a.y, a.z))
    const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length()
    t.applyCameraPoseForTest({ position: [center.x, center.y, center.z + size * 1.5], target: center.toArray() })
    const comparisons = []
    for (const impostors of [false, true]) {
      const paired = []
      for (const init of [before.initAtomisticRenderer, after.initAtomisticRenderer]) {
        const r = init(t.scene, { independentColors: true })
        r.setMode('ballstick'); r.update({ ...sparse, sphereImpostors: impostors })
        const images = [t.renderedPixelCensus()]
        if (r.applyCompactFrame) {
          if (!r.applyCompactFrame(frame)) throw new Error('Compact frame refused')
        } else {
          const expanded = expandMdAtomFrame(frame); r.applyPositionLerp(expanded, expanded, 0)
        }
        images.push(t.renderedPixelCensus())
        const alphas = new Map(sparse.atoms.map(a => [a.helix_id, .6]))
        const colors = new Map(sparse.atoms.map(a => [a.helix_id, 0x3a79bc]))
        r.setClusterDisplay(alphas, colors); images.push(t.renderedPixelCensus())
        const meshes = t.scene.children.filter(m => m.isInstancedMesh && /^atom(Spheres|Bonds)$/.test(m.name))
        window.__uploadAudit.tracked = new Set(meshes.flatMap(m => [m.instanceColor.array, m._instanceAlpha.array]))
        window.__uploadAudit.calls = window.__uploadAudit.bytes = 0
        r.setClusterDisplay(alphas, colors); images.push(t.renderedPixelCensus())
        const uploads = { calls: window.__uploadAudit.calls, bytes: window.__uploadAudit.bytes }
        window.__uploadAudit.tracked = null
        const dynamicMatrices = meshes.every(m => m.instanceMatrix.usage === THREE.DynamicDrawUsage)
        t.scene.updateMatrixWorld(true)
        const a = sparse.atoms[0]
        const ray = new THREE.Raycaster(new THREE.Vector3(a.x + .2, a.y - .1, a.z + 20), new THREE.Vector3(0, 0, -1))
        paired.push({ images, uploads, dynamicMatrices, pick: r.raycastPick(ray)?.atom.serial })
        r.dispose()
      }
      comparisons.push({ mode: impostors ? 'impostors' : 'spheres', paired })
    }
    const queues = []
    for (const init of [oldQueue.initTrajectoryStream, newQueue.initTrajectoryStream]) {
      let release
      const reads = [], applied = []
      const stream = init({ total: 100, live: () => true,
        load: async start => { reads.push(start); if (start === 0) await new Promise(r => { release = r }); return start },
        apply: index => applied.push(index) })
      const active = stream.ensure(0)
      while (!release) await Promise.resolve()
      const scrubs = [8, 16, 24, 32, 40, 48].map(i => (stream.seek ?? stream.ensure)(i))
      release(); await Promise.all([active, ...scrubs])
      queues.push({ reads, applied })
    }
    return { atoms: model.atoms.length, comparisons, queues }
  }, model)
  for (const { mode, paired } of result.comparisons) {
    expect(paired[0].pick, mode).toBeDefined()
    expect(paired[1].pick, mode).toBe(paired[0].pick)
    for (let i = 0; i < paired[0].images.length; i++) {
      expect(paired[0].images[i].visible, mode).toBeGreaterThan(100)
      expect(paired[1].images[i].pixelHash, `${mode} state ${i}`).toBe(paired[0].images[i].pixelHash)
    }
    expect(paired[0].uploads.calls).toBeGreaterThan(0)
    expect(paired[1].uploads.calls).toBe(0)
    expect(paired[1].uploads.bytes).toBe(0)
    expect(paired[1].dynamicMatrices).toBe(true)
  }
  expect(result.queues[0].reads).toEqual([0, 8, 16, 24, 32, 40, 48])
  expect(result.queues[1].reads).toEqual([0, 48])
  expect(result.queues[1].applied.at(-1)).toBe(48)
  expect(errors).toEqual([])
  console.log('loading open verification', JSON.stringify(result))
})
