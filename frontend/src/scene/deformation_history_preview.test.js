// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createDeformationHistoryPreview } from './deformation_history_preview.js'
import { buildDeformationPreviewLayer } from './part_dna_comparison_layer.js'
import { dnaComponent, dnaRecord, dnaRow } from '../test-helpers/part_dna_comparison.js'

const owned = []
const component = () => ({ ...dnaComponent(), component_kind: 'deformation-preview-dna', component_version: 1 })
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
