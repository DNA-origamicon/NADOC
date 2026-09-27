/** Paired renderer benchmarks. Baseline module is read from Git, never written. */
import { execFileSync } from 'node:child_process'
import { performance } from 'node:perf_hooks'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { initAtomisticRenderer } from '../src/scene/atomistic_renderer.js'

const revision = process.argv[2]
if (!revision) throw new Error('Pass the baseline Git revision')
const currentUrl = new URL('../src/scene/atomistic_renderer.js', import.meta.url)
const source = execFileSync('git', ['show', `${revision}:frontend/src/scene/atomistic_renderer.js`], { encoding: 'utf8' })
  .replace(/from ['"]([^'"]+)['"]/g, (_, spec) => `from '${spec.startsWith('.') ? new URL(spec, currentUrl).href : import.meta.resolve(spec)}'`)
const baseline = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const median = a => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)]
const results = []
for (const n of [30000, 150000]) {
  const atoms = Array.from({ length: n }, (_, i) => ({ serial: i * 2 + 1,
    element: ['C', 'N', 'O', 'P'][i % 4], helix_id: `h${i % 2}`, strand_id: 's',
    x: (i % 100) * .15, y: Math.floor(i / 100) * .2, z: .1 * (i % 2) }))
  const bonds = atoms.flatMap((a, i) => i % 100 ? [[atoms[i - 1].serial, a.serial]] : [])
  const from = new Float64Array(n * 6), to = new Float64Array(n * 6)
  for (const a of atoms) {
    from.set([a.x, a.y, a.z], a.serial * 3)
    to.set([a.x + .15, a.y - .2, a.z + .1], a.serial * 3)
  }
  const setups = [baseline.initAtomisticRenderer, initAtomisticRenderer].map(init => {
    const scene = new THREE.Scene(), renderer = init(scene)
    renderer.setMode('ballstick'); renderer.update({ atoms, bonds })
    return { scene, renderer }
  })
  const ct = [{ helix_ids: ['h0'], center: new THREE.Vector3(1, 2, 3),
    dummy: new THREE.Vector3(2, 3, 4), incrRot: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), .1) }]
  const frames = [0, 1].map(k => ({ atoms: atoms.map(a => ({ ...a, x: a.x + k * .1 })), bonds }))
  const operations = {
    exact_snapshot: r => r.applyPositionLerp(to, to, 0),
    interpolation: (r, k) => r.applyPositionLerp(from, to, .2 + k * .01),
    cluster_interpolation: (r, k) => r.applyPositionLerp(from, to, .2 + k * .01, from, ct, new Set(['h0'])),
    live_md: (r, k) => r.updateFrame(frames[k % 2]),
  }
  for (const [operation, run] of Object.entries(operations)) {
    for (const { renderer } of setups) for (let k = 0; k < 15; k++) run(renderer, k)
    const times = [[], []]
    for (let k = 0; k < 31; k++) {
      for (const i of (k % 2 ? [1, 0] : [0, 1])) {
        const start = performance.now(); run(setups[i].renderer, k)
        times[i].push(performance.now() - start)
      }
      const meshes = setups.map(({ scene }) => scene.children.filter(m => m.isInstancedMesh))
      assert.equal(meshes[0].length, meshes[1].length)
      meshes[0].forEach((mesh, i) => {
        assert.deepEqual(mesh.instanceMatrix.array, meshes[1][i].instanceMatrix.array)
        if (mesh.instanceColor) assert.deepEqual(mesh.instanceColor.array, meshes[1][i].instanceColor.array)
      })
    }
    const beforeMs = median(times[0]), afterMs = median(times[1])
    const row = { atoms: n, bonds: bonds.length, operation, beforeMs, afterMs, speedup: beforeMs/afterMs, exactBuffers: true }
    results.push(row); console.log(JSON.stringify(row))
  }
  setups.forEach(({ renderer }) => renderer.dispose())
}
console.log(JSON.stringify({ baseline: revision, results }, null, 2))
