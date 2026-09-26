import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { initProteinTraceRenderer, proteinBoxSpec, proteinOvoidSpec, proteinTraceChains } from './protein_trace_renderer.js'

const atom = (id, chain, seq, x, name = 'CA') => ({
  name, chain_id: chain, seq_num: seq,
  helix_id: `__protein__${id}`, strand_id: `__protein__${id}`,
  x, y: 0, z: 0,
})

describe('proteinTraceChains', () => {
  it('uses only C-alpha atoms and keeps attachments/chains separate', () => {
    const chains = proteinTraceChains([
      atom('p1', 'PA', 1, 0), atom('p1', 'PA', 1, 0.1, 'N'),
      atom('p1', 'PA', 2, 0.38), atom('p1', 'PB', 1, 1),
      atom('p2', 'PA', 1, 2),
    ])
    expect(chains.map(c => [c.attachmentId, c.chainId, c.atoms.length])).toEqual([
      ['p1', 'PA', 2], ['p1', 'PB', 1], ['p2', 'PA', 1],
    ])
  })

  it('does not draw a tube across disconnected fragments', () => {
    const chains = proteinTraceChains([
      atom('p1', 'PA', 1, 0), atom('p1', 'PA', 2, 0.38), atom('p1', 'PA', 9, 5),
    ])
    expect(chains.map(c => c.atoms.length)).toEqual([2, 1])
  })
})

describe('proteinOvoidSpec', () => {
  it('centers an ovoid on the protein bounds and pads each radius', () => {
    const spec = proteinOvoidSpec([
      { x: -2, y: -1, z: 0 },
      { x: 4, y: 3, z: 2 },
    ])
    expect(spec.center.toArray()).toEqual([1, 1, 1])
    expect(spec.radii.toArray()).toEqual([3.18, 2.18, 1.18])
  })
})

describe('proteinBoxSpec', () => {
  it('uses the same padded protein bounds for a box', () => {
    const spec = proteinBoxSpec([{ x: -2, y: -1, z: 0 }, { x: 4, y: 3, z: 2 }])
    expect(spec.center.toArray()).toEqual([1, 1, 1])
    expect(spec.size.toArray()).toEqual([6.36, 4.36, 2.36])
  })
})

describe('initProteinTraceRenderer', () => {
  it('builds named photo-compatible meshes and preserves exact all-atom centroid', () => {
    const scene = new THREE.Scene()
    const renderer = initProteinTraceRenderer(scene)
    const atoms = [atom('p1', 'PA', 1, 0), atom('p1', 'PA', 2, 0.38), atom('p1', 'PA', 2, 1.0, 'CB')]
    renderer.setMode('trace')
    renderer.update({ atoms })
    expect(scene.getObjectByName('proteinTrace')).not.toBeNull()
    expect(renderer.centroidOf(a => a.helix_id === '__protein__p1').x).toBeCloseTo(1.38 / 3)

    renderer.applyOxdnaTransforms({ p1: [1, 0, 0, 3, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] })
    expect(renderer.centroidOf(a => a.helix_id === '__protein__p1').x).toBeCloseTo(1.38 / 3 + 3)
    renderer.dispose()
  })

  it('builds one protein-sized ovoid per attachment in cylinder mode', () => {
    const scene = new THREE.Scene()
    const renderer = initProteinTraceRenderer(scene)
    renderer.setMode('ovoid')
    renderer.update({ atoms: [atom('p1', 'PA', 1, 0), atom('p1', 'PA', 2, 3)] })
    expect(scene.getObjectByName('proteinOvoid')).not.toBeNull()
    expect(scene.getObjectByName('proteinTrace').children).toHaveLength(1)
    renderer.dispose()
  })

  it('builds one protein-sized box per attachment in hull-prism mode', () => {
    const scene = new THREE.Scene()
    const renderer = initProteinTraceRenderer(scene)
    renderer.setMode('box')
    renderer.update({ atoms: [atom('p1', 'PA', 1, 0), atom('p1', 'PA', 2, 3)] })
    const box = scene.getObjectByName('proteinBox')
    expect(box).not.toBeNull()
    expect(box.geometry.type).toBe('BoxGeometry')
    renderer.dispose()
  })
})

it.each(['trace'])('reuses unchanged %s geometry but refreshes metadata and detects in-place edits', mode => {
  const scene = new THREE.Scene(), r = initProteinTraceRenderer(scene)
  let atoms = [atom('p1', 'A', 1, 0), atom('p1', 'A', 2, .38)]
  r.setMode(mode); r.update({ atoms })
  const mesh = () => scene.getObjectByName('proteinTrace').children[0]
  const original = mesh().geometry
  const coordinates = original.attributes.position.array.slice()
  atoms = atoms.map(a => ({ ...a, serial: 123 }))
  r.update({ atoms })
  expect(mesh().geometry).toBe(original)
  expect(mesh().geometry.attributes.position.array).toEqual(coordinates)
  expect(r.raycastPick({ intersectObjects: objects => [{ object: objects[0], distance: 2 }] }).atom).toBe(atoms[mode === 'trace' ? 1 : 0])
  expect(r.centroidOf(a => a.serial === 123).x).toBeCloseTo(.19)
  r.beginLiveTransform(() => true); r.applyLiveTransform(new THREE.Matrix4().makeTranslation(4, 0, 0))
  r.update({ atoms }); expect(r.centroidOf().x).toBeCloseTo(.19)
  atoms[1].x = .7; r.update({ atoms })
  expect(mesh().geometry).not.toBe(original)
  expect(r.centroidOf().x).toBeCloseTo(.35)
  const changed = mesh().geometry
  atoms[1].chain_id = 'B'; r.update({ atoms })
  expect(mesh().geometry).not.toBe(changed)
  r.setMode('off'); r.update({ atoms }); r.setMode(mode)
  expect(mesh()).toBeDefined()
  r.dispose(); expect(scene.children).toHaveLength(0)
})
