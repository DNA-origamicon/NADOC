/** Paired CPU benchmarks; baseline code is loaded without changing the worktree. */
import { execFileSync } from 'node:child_process'
import { performance } from 'node:perf_hooks'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { initAtomisticRenderer } from '../src/scene/atomistic_renderer.js'
import { initSurfaceRenderer } from '../src/scene/surface_renderer.js'

const revision = process.argv[2]
if (!revision) throw new Error('Pass the baseline Git revision')
async function original(file) {
  const url = new URL(`../src/scene/${file}.js`, import.meta.url)
  const source = execFileSync('git', ['show', `${revision}:frontend/src/scene/${file}.js`], { encoding: 'utf8' })
    .replace(/from ['"]([^'"]+)['"]/g, (_, spec) => `from '${spec.startsWith('.') ? new URL(spec, url).href : import.meta.resolve(spec)}'`)
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
}
const oldAtoms = (await original('atomistic_renderer')).initAtomisticRenderer
const oldSurface = (await original('surface_renderer')).initSurfaceRenderer
const median = a => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)]
const results = []
function measure(operation, scale, setups, run, compare) {
  for (const s of setups) for (let k = 0; k < 10; k++) run(s, k)
  const times = [[], []]
  for (let k = 0; k < 21; k++) {
    for (const i of k % 2 ? [1, 0] : [0, 1]) {
      const start = performance.now(); run(setups[i], k)
      times[i].push(performance.now() - start)
    }
    compare(...setups)
  }
  const beforeMs = median(times[0]), afterMs = median(times[1])
  const row = { operation, ...scale, beforeMs, afterMs, speedup: beforeMs / afterMs, exactBuffers: true }
  results.push(row)
  console.error(JSON.stringify(row))
}
for (const n of process.argv.includes('--surface-only') ? [] : [30000, 150000]) {
  const atoms = Array.from({ length: n }, (_, i) => ({ serial: i * 2 + 1,
    element: ['C', 'N', 'O', 'P'][i % 4], helix_id: `h${i % 12}`, strand_id: `s${i % 8}`,
    bp_index: Math.floor(i / 24), direction: 'FORWARD',
    x: (i % 100) * .15, y: Math.floor(i / 100) * .2, z: .1 * (i % 2) }))
  const bonds = atoms.flatMap((a, i) => i % 100 ? [[atoms[i - 1].serial, a.serial]] : [])
  const setups = [oldAtoms, initAtomisticRenderer].map(init => {
    const scene = new THREE.Scene(), renderer = init(scene, { independentColors: true })
    renderer.setMode('ballstick'); renderer.update({ atoms, bonds })
    return { scene, renderer }
  })
  const colors = new Map(atoms.map((a, i) => [`${a.helix_id}:${a.bp_index}:${a.direction}`, [0x257abc, 0xdead21, 0x883366][i % 3]]))
  const alphas = new Map([...colors.keys()].map((key, i) => [key, i % 3 ? .35 : 1]))
  const selections = [null, { strandIds: ['s0', 's3'], bases: [], domains: [] }]
  function compare(a, b) {
    const meshes = [a, b].map(s => s.scene.children.filter(m => m.isInstancedMesh))
    assert.equal(meshes[0].length, meshes[1].length)
    meshes[0].forEach((m, i) => {
      assert.deepEqual(m.instanceColor.array, meshes[1][i].instanceColor.array)
      assert.deepEqual(m._instanceAlpha?.array, meshes[1][i]._instanceAlpha?.array)
      assert.deepEqual(m.instanceMatrix.array, meshes[1][i].instanceMatrix.array)
    })
  }
  measure('cpk_selection', { atoms: n, bonds: bonds.length }, setups,
    (s, k) => s.renderer.highlight(selections[k % 2]), compare)
  measure('cluster_colours_fades', { atoms: n, bonds: bonds.length }, setups,
    s => s.renderer.setClusterDisplay(alphas, colors), compare)
  setups.forEach(s => s.renderer.applyScalarColors(colors))
  measure('scalar_selection_fades', { atoms: n, bonds: bonds.length }, setups,
    (s, k) => s.renderer.highlight(selections[k % 2]), compare)
  setups.forEach(s => s.renderer.dispose())
}
for (const side of [150, 400]) {
  const vertices = [], faces = [], vertex_colors = []
  for (let y = 0; y < side; y++) for (let x = 0; x < side; x++) {
    vertices.push(x * .1, y * .1, Math.sin(x * .1) * Math.cos(y * .1))
    vertex_colors.push(.2, x / side, y / side)
    if (x && y) {
      const i = y * side + x
      faces.push(i, i - 1, i - side, i - 1, i - side - 1, i - side)
    }
  }
  const data = { vertices, faces, vertex_colors, scalar: true }
  const movingVertices = [0, 1].map(k => vertices.map((v, i) =>
    v + (i % 3 === 2 ? Math.sin(i * .01 + k) * .02 : k * .01)))
  const setups = [oldSurface, initSurfaceRenderer].map(init => {
    const renderer = init(new THREE.Scene()); renderer.update(data)
    return { renderer, data: structuredClone(data) }
  })
  function compare(a, b) {
    const geometries = [a, b].map(s => s.renderer.getMesh().geometry)
    for (const name of ['position', 'normal', 'color'])
      assert.deepEqual(geometries[0].attributes[name].array, geometries[1].attributes[name].array)
    assert.deepEqual(geometries[0].index.array, geometries[1].index.array)
  }
  const operations = {
    scalar_surface_repeat: () => {},
    scalar_surface_recolour: (d, k) => { d.vertex_colors[0] = k / 100 },
    scalar_surface_motion: (d, k) => { d.vertices = movingVertices[k % 2] },
  }
  for (const [name, mutate] of Object.entries(operations)) measure(name,
    { vertices: vertices.length / 3, faces: faces.length / 3 }, setups,
    (s, k) => { mutate(s.data, k); s.renderer.applyPositionLerp(s.data, s.data, 0) }, compare)
  setups.forEach(s => s.renderer.dispose())
}
console.log(JSON.stringify({ baseline: revision, results }, null, 2))
