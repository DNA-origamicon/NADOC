/** CPU attribution only. Run through scripts/validation_guard.sh. */
import inspector from 'node:inspector'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import * as THREE from 'three'
import { initAtomisticRenderer } from '../src/scene/atomistic_renderer.js'

if (process.env.NADOC_VALIDATION_SCOPE !== '1') throw new Error('Use validation_guard.sh')
const atoms = Array.from({ length: 150000 }, (_, i) => ({ serial: i * 2 + 1,
  element: ['C', 'N', 'O', 'P'][i % 4], helix_id: `h${i % 2}`, strand_id: 's',
  x: (i % 100) * .15, y: Math.floor(i / 100) * .2, z: .1 * (i % 2) }))
const bonds = atoms.flatMap((a, i) => i % 100 ? [[atoms[i - 1].serial, a.serial]] : [])
const frames = [0, 1].map(k => ({ atoms: atoms.map(a => ({ ...a, x: a.x + k * .1 })), bonds }))
const from = new Float64Array(atoms.length * 6), to = new Float64Array(atoms.length * 6)
for (const a of atoms) {
  from.set([a.x, a.y, a.z], a.serial * 3)
  to.set([a.x + .15, a.y - .2, a.z + .1], a.serial * 3)
}
const renderer = initAtomisticRenderer(new THREE.Scene())
renderer.setMode('ballstick'); renderer.update({ atoms, bonds })
const session = new inspector.Session()
session.connect()
const post = (method, params = {}) => new Promise((resolve, reject) => {
  session.post(method, params, (err, result) => err ? reject(err) : resolve(result))
})
const results = []
try {
  await post('Profiler.enable')
  for (const [operation, run] of Object.entries({
    live_md: k => renderer.updateFrame(frames[k % 2]),
    interpolation: k => renderer.applyPositionLerp(from, to, .2 + (k % 10) * .01),
  })) {
    for (let k = 0; k < 15; k++) run(k)
    await post('Profiler.start')
    for (let k = 0; k < 100; k++) run(k)
    const { profile } = await post('Profiler.stop')
    const counts = new Map()
    for (const id of profile.samples) counts.set(id, (counts.get(id) || 0) + 1)
    const rows = profile.nodes.map(n => ({ function: n.callFrame.functionName,
      source: n.callFrame.url, line: n.callFrame.lineNumber + 1, selfSamples: counts.get(n.id) || 0 }))
      .filter(r => r.selfSamples).sort((a, b) => b.selfSamples - a.selfSamples)
    results.push({ operation, samples: profile.samples.length, topSelf: rows.slice(0, 25) })
  }
} finally {
  session.disconnect(); renderer.dispose()
}
console.log(JSON.stringify({ scope: 'Node CPU diagnostic; 100 warmed updates per operation, 150k atoms. Sampling counts are not user latency or GPU timing.',
  rendererSha256: createHash('sha256').update(readFileSync(new URL('../src/scene/atomistic_renderer.js', import.meta.url))).digest('hex'), results }, null, 2))
