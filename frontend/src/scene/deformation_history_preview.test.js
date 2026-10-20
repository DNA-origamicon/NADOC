// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createDeformationHistoryPreview } from './deformation_history_preview.js'
import { buildPartDnaComparisonLayer, buildDeformationPreviewLayer } from './part_dna_comparison_layer.js'
import { dnaComponent, dnaRecord, dnaRow } from '../test-helpers/part_dna_comparison.js'

const owned = []
const component = () => ({ ...dnaComponent(), component_kind: 'deformation-preview-dna', component_version: 2 })
function setup() {
  const scene = new THREE.Scene(), live = new THREE.Group(); scene.add(live)
  let current = live
  const preview = createDeformationHistoryPreview({ scene, getLiveRoot: () => current })
  owned.push(preview)
  return { scene, live, preview, replaceLive: value => { current = value; scene.add(value) } }
}
function nodes(root) { const result = []; root.traverse(n => { if (n.geometry) result.push(n) }); return result }
afterEach(() => { for (const owner of owned.splice(0)) owner.dispose(); vi.restoreAllMocks() })

describe('owned native deformation history display', () => {
  it('isolates real native panes from sibling geometry and restores the camera on repeated sessions', () => {
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
    const live = new THREE.Group(), arc = new THREE.Line(), light = new THREE.AmbientLight()
    scene.add(live, arc, light)
    for (let index = 0; index < 2; index++) {
      const preview = createDeformationHistoryPreview({ scene, camera, getLiveRoot: () => live }); owned.push(preview)
      preview.open({ before: component(), candidate: component() })
      const visible = scene.children.filter(child => child.name === 'privateDeformationPreview')
      for (const root of visible) root.traverse(node => expect(camera.layers.test(node.layers)).toBe(true))
      expect(camera.layers.test(arc.layers)).toBe(false); expect(arc.visible).toBe(true); expect(live.visible).toBe(true)
      preview.show('before'); preview.replaceCandidate(null)
      expect(visible[0].visible).toBe(true)
      preview.replaceCandidate(component()); preview.show('candidate')
      preview.dispose()
      expect(scene.children).toEqual([live, arc, light]); expect(camera.layers.mask).toBe(1); expect(light.layers.mask).toBe(1)
    }
  })

  it('keeps the saved scene and input packet intact while switching before/candidate/off', () => {
    const { scene, live, preview } = setup(), before = component(), candidate = component()
    const original = JSON.stringify({ before, candidate })
    preview.open({ before, candidate })
    expect(scene.children).toHaveLength(3); expect(live.visible).toBe(false)
    const [prefix, result] = scene.children.slice(1)
    expect(prefix.visible).toBe(false); expect(result.visible).toBe(true)
    preview.show('before'); expect(prefix.visible).toBe(true); expect(result.visible).toBe(false)
    preview.show('off'); expect(prefix.visible).toBe(false); expect(result.visible).toBe(false); expect(live.visible).toBe(true)
    preview.show('candidate'); expect(live.visible).toBe(false); expect(result.visible).toBe(true)
    expect(JSON.stringify({ before, candidate })).toBe(original)
    preview.dispose(); expect(scene.children).toEqual([live]); expect(live.visible).toBe(true)
  })

  it('preserves a hidden live scene and never changes visibility on a replacement live owner', () => {
    const { live, preview, replaceLive } = setup(); live.visible = false
    preview.open({ before: component(), candidate: component() })
    preview.show('off'); expect(live.visible).toBe(false)
    preview.show('candidate')
    const replacement = new THREE.Group(); replacement.visible = false; replaceLive(replacement)
    preview.dispose(); expect(replacement.visible).toBe(false); expect(live.visible).toBe(false)
  })

  it('releases each superseded private instance/material once without touching shared templates', () => {
    const { scene, preview } = setup(); preview.open({ before: component(), candidate: component() })
    const previous = scene.children[2], meshes = nodes(previous)
    const shared = [...new Set(meshes.filter(n => n.geometry.userData.shared).map(n => n.geometry))]
    const sharedSpies = shared.map(g => vi.spyOn(g, 'dispose'))
    const resources = [...new Set(meshes.map(n => n.material)), ...meshes.filter(n => n.isInstancedMesh)]
    const disposals = resources.map(r => vi.spyOn(r, 'dispose'))
    for (let index = 0; index < 5; index++) preview.replaceCandidate(component())
    expect(scene.children).toHaveLength(3); expect(previous.parent).toBe(null)
    preview.dispose(); preview.dispose()
    for (const spy of disposals) expect(spy).toHaveBeenCalledOnce()
    for (const spy of sharedSpies) expect(spy).not.toHaveBeenCalled()
    for (const geometry of shared) expect(geometry.userData.shared).toBe(true)
  })

  it('retains the last complete display if a candidate cannot be rendered and cleans partial Open', () => {
    const { scene, live, preview } = setup()
    const invalid = component(); invalid.nucleotides.pop()
    expect(() => preview.open({ before: component(), candidate: invalid })).toThrow()
    expect(scene.children).toEqual([live]); expect(live.visible).toBe(true)
    preview.open({ before: component(), candidate: component() })
    const old = scene.children[2]
    expect(() => preview.replaceCandidate(invalid)).toThrow()
    expect(scene.children[2]).toBe(old); expect(old.visible).toBe(true)
  })

  it('clears a disabled candidate without retaining obsolete geometry and restores it on update', () => {
    const { scene, live, preview } = setup()
    preview.open({ before: component(), candidate: component() })
    preview.replaceCandidate(null)
    expect(scene.children).toHaveLength(2); expect(live.visible).toBe(true)
    preview.replaceCandidate(component())
    expect(scene.children).toHaveLength(3); expect(live.visible).toBe(false)
  })


  it('reuses a detached buffer with fresh native curves, beads, slabs and connections identical to a rebuild', () => {
    const { scene, preview } = setup()
    const value = component(), axis = value.helix_axes[0]
    value.display_topology.helices[0].length_bp = 9
    value.display_topology.strands[0].domains[0].end_bp = 8
    value.nucleotides = Array.from({ length: 9 }, (_, i) => dnaRow(dnaRecord(i)))
    axis.end = [0, 0, 2.72]; axis.segments[0].end = axis.end; axis.segments[0].bp_hi = 8
    axis.samples = [[0, 0, 0], [.5, .2, 2.38], [0, 0, 2.72]]
    axis.segments[0].samples = axis.samples
    value.display_topology.crossovers = [{ id: 'cross', half_a: { helix_id: 'h', index: 0, strand: 'FORWARD' },
      half_b: { helix_id: 'h', index: 8, strand: 'FORWARD' }, extra_bases: null }]
    preview.open({ before: value, candidate: value })
    const initial = scene.children[2]
    preview.replaceCandidate(value)
    expect(initial.parent).toBe(null)
    const changed = structuredClone(value)
    const rotation = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4)
    const rotate = p => new THREE.Vector3(...p).applyQuaternion(rotation).toArray()
    const shift = p => rotate(p).map((x, i) => x + [4, -2, 0][i])
    changed.nucleotides = Array.from({ length: 9 }, (_, i) => {
      const n = dnaRecord(i)
      for (const field of ['backbone_position', 'base_position', 'slab_position']) n[field] = shift(n[field])
      n.helical_site.axis_point = shift(n.helical_site.axis_point)
      n.helical_site.radial_hat = rotate(n.helical_site.radial_hat)
      n.base_normal = rotate(n.base_normal); n.axis_tangent = rotate(n.axis_tangent)
      n.slab_quaternion = rotation.clone().multiply(new THREE.Quaternion(...n.slab_quaternion)).toArray()
      return dnaRow(n)
    })
    const ax = changed.helix_axes[0]
    ax.start = shift(ax.start); ax.end = shift(ax.end)
    ax.samples = ax.samples.map(shift); ax.samples[1][0] += 1
    ax.segments[0].start = ax.start; ax.segments[0].end = ax.end; ax.segments[0].samples = ax.samples
    const untouched = JSON.stringify(changed)
    preview.replaceCandidate(changed)
    expect(scene.children[2]).toBe(initial)
    const fresh = buildDeformationPreviewLayer(changed, new THREE.Scene()); owned.push(fresh)
    function visible(root) {
      const result = []
      root.updateMatrixWorld(true)
      root.traverseVisible(n => {
        if (!n.geometry) return
        result.push({ name: n.name, transform: n.matrixWorld.elements,
          positions: [...(n.geometry.attributes.position?.array ?? [])],
          instances: n.instanceMatrix ? [...n.instanceMatrix.array] : null,
          colors: n.instanceColor ? [...n.instanceColor.array] : null })
      })
      return result.sort((a, b) => a.name.localeCompare(b.name))
    }
    expect(visible(initial)).toEqual(visible(fresh.root))
    expect(JSON.stringify(changed)).toBe(untouched)
    const bad = structuredClone(changed); bad.nucleotides.pop()
    expect(() => preview.replaceCandidate(bad)).toThrow()
    expect(scene.children[2]).toBe(initial)
    expect(visible(initial)).toEqual(visible(fresh.root))
  })

  it('rebuilds when an unchanged-size candidate changes its scalar inventory', () => {
    const { scene, preview } = setup()
    preview.open({ before: component(), candidate: component() })
    const original = scene.children[2]
    preview.replaceCandidate(component())
    const changed = component()
    changed.display_topology.strands[0].is_reference = true
    changed.nucleotides = [0, 1].map(i => dnaRow({ ...dnaRecord(i), is_reference: true }))
    preview.replaceCandidate(changed)
    expect(scene.children[2]).not.toBe(original)
    expect(original.children).toHaveLength(0)
    const fresh = buildDeformationPreviewLayer(changed, new THREE.Scene()); owned.push(fresh)
    const alpha = root => nodes(root).filter(n => n._instanceAlpha).map(n => [...n._instanceAlpha.array])
    expect(alpha(scene.children[2])).toEqual(alpha(fresh.root))
  })

  it('preserves distinct inserted-copy native matrices when reusing a buffer', () => {
    const { scene, preview } = setup(), value = component()
    value.display_topology.helices[0].loop_skips = [{ bp_index: 0, delta: 1 }]
    const records = [dnaRecord(0), { ...dnaRecord(0), copy_k: 1 }, dnaRecord(1)]
    for (const field of ['backbone_position', 'base_position', 'slab_position'])
      records[1][field] = records[1][field].map((x, i) => x + (i === 2 ? .17 : 0))
    value.nucleotides = records.map(dnaRow)
    preview.open({ before: value, candidate: value })
    const changed = structuredClone(value)
    changed.nucleotides = records.map(n => dnaRow({ ...n,
      ...Object.fromEntries(['backbone_position', 'base_position', 'slab_position'].map(field =>
        [field, n[field].map((x, i) => x + (i === 0 ? 9 : 0))])) }))
    preview.replaceCandidate(changed)
    const fresh = buildDeformationPreviewLayer(changed, new THREE.Scene()); owned.push(fresh)
    const matrices = root => nodes(root).filter(n => n.isInstancedMesh && n.visible)
      .map(n => [n.name, [...n.instanceMatrix.array]]).sort((a, b) => a[0].localeCompare(b[0]))
    expect(matrices(scene.children[2])).toEqual(matrices(fresh.root))
  })

  it('reduces only axis tessellation while retaining every ordinary native curve control point', () => {
    const value = component(), axis = value.helix_axes[0]
    value.display_topology.helices[0].length_bp = 64
    value.display_topology.strands[0].domains[0].end_bp = 63
    value.nucleotides = Array.from({ length: 64 }, (_, i) => dnaRow(dnaRecord(i)))
    axis.end = [0, 0, 63 * .34]; axis.segments[0].end = axis.end; axis.segments[0].bp_hi = 63
    axis.samples = Array.from({ length: 10 }, (_, i) => [Math.sin(i / 9 * Math.PI), 0, i * 7 * .34])
    axis.segments[0].samples = axis.samples
    const preview = buildDeformationPreviewLayer(value, new THREE.Scene()); owned.push(preview)
    const { component_kind, ...comparison } = value
    comparison.component_version = 3
    const full = buildPartDnaComparisonLayer(comparison, new THREE.Scene()); owned.push(full)
    const tubes = root => nodes(root).filter(n => n.geometry.type === 'TubeGeometry').map(n => n.geometry.parameters)
    const actual = tubes(preview.root), expected = tubes(full.root)
    expect(actual).toHaveLength(expected.length)
    for (let i = 0; i < actual.length; i++) {
      expect(actual[i].path.points).toEqual(expected[i].path.points)
      expect(actual[i].tubularSegments).toBeLessThan(expected[i].tubularSegments)
      expect(actual[i].radius).toBe(expected[i].radius)
    }
  })

  it('keeps setup-only periodic continuations hidden after buffer updates and scene traversal', () => {
    const { scene, preview } = setup(), value = component()
    value.display_topology.forced_ligations = [{ id: 'seam', three_prime_helix_id: 'h', three_prime_bp: 1,
      three_prime_direction: 'FORWARD', five_prime_helix_id: 'h', five_prime_bp: 0,
      five_prime_direction: 'FORWARD', extra_bases: null, is_periodic_seam: true }]
    preview.open({ before: value, candidate: value })
    for (let i = 0; i < 3; i++) {
      preview.replaceCandidate(structuredClone(value))
      scene.updateMatrixWorld(true)
      expect(scene.children[2].getObjectByName('polymerizationContinuation').visible).toBe(false)
    }
  })

  it('passes scoped samples to the unchanged native renderer instead of straightening them', () => {
    const value = component(), axis = value.helix_axes[0]
    // Transport/render fixture: native axis sampling uses bp 0, 7, then the last bp.
    value.display_topology.helices[0].length_bp = 9
    value.display_topology.strands[0].domains[0].end_bp = 8
    value.nucleotides = Array.from({ length: 9 }, (_, index) => dnaRow(dnaRecord(index)))
    axis.end = [0, 0, 2.72]; axis.segments[0].end = axis.end; axis.segments[0].bp_hi = 8
    axis.segments[0].samples = [[0, 0, 0], [.5, .2, 2.38], [0, 0, 2.72]]
    const scene = new THREE.Scene(), layer = buildDeformationPreviewLayer(value, scene); owned.push(layer)
    const axes = nodes(layer.root).filter(node => node.name === 'axisLine')
    expect(axes).toHaveLength(2)
    const curve = axes.find(node => node.geometry.type === 'TubeGeometry')
    expect(curve.visible).toBe(true)
    curve.geometry.computeBoundingBox()
    expect(curve.geometry.boundingBox.max.x).toBeGreaterThan(.4)
    expect(axes.find(node => node !== curve).visible).toBe(false)
  })
})

it('opens an owned creation prefix without any provisional candidate and disposes it cleanly', () => {
  const { scene, live, preview } = setup()
  preview.open({ mode: 'create', awaiting_parameters: true, before: component(), candidate: null })
  expect(scene.children).toHaveLength(2); expect(live.visible).toBe(false)
  expect(scene.children.find(node => node.name === 'privateDeformationPreview').visible).toBe(true)
  preview.replaceCandidate(component()); preview.show('candidate')
  expect(scene.children).toHaveLength(3)
  preview.dispose(); expect(scene.children).toEqual([live]); expect(live.visible).toBe(true)
})


it('allows guide-only Sweep ownership while retaining one fixed prefix and restoring the camera', () => {
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
  const preview = createDeformationHistoryPreview({ scene, camera, allowEmptyCandidate: true })
  owned.push(preview)
  preview.open({ before: component(), candidate: null })
  const prefix = scene.children.find(child => child.name === 'privateDeformationPreview')
  expect(prefix.visible).toBe(true)
  expect(scene.children.filter(child => child.name === 'privateDeformationPreview')).toEqual([prefix])
  preview.replaceCandidate(null); preview.show('before')
  expect(scene.children.filter(child => child.name === 'privateDeformationPreview')).toEqual([prefix])
  preview.dispose()
  expect(scene.children).toHaveLength(0)
  expect(camera.layers.mask).toBe(1)
})
