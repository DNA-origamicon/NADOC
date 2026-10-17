// Usage: node frontend/scripts/bench_assembly_renderer.mjs geometry-response.json [output.json]
// Read-only CPU profile: canonical API geometry in, source build stages out.
// Run under just validate-safe; do not overlap browser/backend validation.
import { readFile, writeFile, stat, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import * as THREE from 'three'
import { decodeAssemblyGeometry } from '../src/viewer/geometry_codec.js'
import { _createSharedInstancingRenderer } from '../src/scene/assembly_renderer_shared.js'

const [input, output] = process.argv.slice(2)
if (!input) throw new Error('Supply a saved assembly geometry response JSON file')
const started = performance.now()
const wire = (await stat(input)).isDirectory()
  ? await (async () => {
    const sources = {}, instances = {}
    for (const file of (await readdir(input)).filter(file => file.endsWith('.json')).sort()) {
      const id = file.slice(0, -5)
      sources[id] = JSON.parse(await readFile(join(input, file), 'utf8'))
      instances[id] = id
    }
    return { sources, instances }
  })()
  : JSON.parse(await readFile(input, 'utf8'))
const parsed = performance.now()
const decoded = decodeAssemblyGeometry(wire)
const decodedAt = performance.now()
let assembly = { instances: Object.keys(decoded.instances).map(id => {
  const key = typeof wire.instances?.[id] === 'string' ? wire.instances[id] : id
  return { id, source: { type: 'file', path: key }, geometrySourceKey: `f:/${key}:1:`,
    representation: 'cylinders', visible: true, transform: { values: new THREE.Matrix4().elements } }
}) }
const scene = new THREE.Scene()
const api = { getAssemblyGeometry: async () => decoded,
  getInstanceGeometry: async id => decoded.instances[id], getInstanceProteinGeometry: async () => ({ atoms: [] }) }
const store = { getState: () => ({ currentAssembly: assembly, coloringMode: 'strand' }), subscribe: () => () => {} }
const renderer = _createSharedInstancingRenderer({ scene, api, store })
const phases = []
try {
  for (const representation of ['cylinders', 'full', 'beads', 'cylinders', 'full']) {
    assembly = { ...assembly, instances: assembly.instances.map(instance => ({ ...instance, representation })) }
    const before = performance.now()
    await renderer.rebuild(assembly)
    phases.push({ representation, elapsed_ms: performance.now() - before,
      sources: scene.children.filter(group => group.userData.sharedSource).map(group => ({
        source: group.userData.sharedSource, build: group.userData.assemblyBuildTimings,
      })) })
  }
  const result = { input, parse_ms: parsed - started, decode_ms: decodedAt - parsed,
    instances: assembly.instances.length, phases }
  const text = JSON.stringify(result, null, 2)
  if (output) await writeFile(output, text + '\n')
  else process.stdout.write(text + '\n')
} finally { renderer.dispose() }
