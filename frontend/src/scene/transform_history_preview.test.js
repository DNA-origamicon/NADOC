// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createTransformHistoryPreview, buildTransformPreviewLayer } from './transform_history_preview.js'
import { transformComponent, transformPacket } from '../test-helpers/transform_preview.js'
import { dnaRecord } from '../test-helpers/part_dna_comparison.js'
import { store } from '../state/store.js'

const owners = []
afterEach(() => { for (const owner of owners.splice(0)) owner.dispose(); vi.restoreAllMocks() })
function setup() {
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(), live = new THREE.Group(), light = new THREE.AmbientLight()
  scene.add(live, light)
  const preview = createTransformHistoryPreview({ scene, camera }); owners.push(preview)
  return { scene, camera, live, light, preview }
}
function flexibleJunctionComponent() {
  const value = transformComponent(), topology = value.display_topology
  const helix = topology.helices[0], domain = topology.strands[0].domains[0], placement = topology.cluster_transforms[0]
  topology.helices = ['a', 'b'].map((id, i) => ({ ...helix, id, length_bp: 3,
    axis_start: { x: i * 3, y: 0, z: 0 }, axis_end: { x: i * 3, y: 0, z: .68 } }))
  topology.strands[0].domains = ['a', 'b'].map(helix_id => ({ ...domain, helix_id, end_bp: 2 }))
  topology.cluster_transforms = ['a', 'b'].map(id => ({ ...placement, id: `p-${id}`, helix_ids: [id] }))
  const anchor = (domain_index, bp_index) => ({ strand_id: 's', domain_index, bp_index, direction: 'FORWARD' })
  const segment = [anchor(0, 1), anchor(0, 2), anchor(1, 0), anchor(1, 1)]
  topology.flexible_segment_marks = segment.map((a, i) => ({ id: `mark-${i}`, ...a }))
  topology.flexible_connections = [{ id: 'flex', cluster_a_id: 'p-a', cluster_b_id: 'p-b',
    anchor_a: anchor(0, 0), anchor_b: anchor(1, 2), segment_bead_keys: segment,
    n_ss_bases: 4, contour_length_nm: 5 }]
  topology.forced_ligations = [{ id: 'junction', three_prime_helix_id: 'a', three_prime_bp: 2,
    three_prime_direction: 'FORWARD', five_prime_helix_id: 'b', five_prime_bp: 0,
    five_prime_direction: 'FORWARD', extra_bases: null, is_periodic_seam: false }]
  value.nucleotides = topology.helices.flatMap((h, i) => [0, 1, 2].map(bp => {
    const n = dnaRecord(bp), shift = v => v.map((x, axis) => x + (axis === 0 ? i * 3 : 0))
    return { ...n, helix_id: h.id, domain_index: i, is_five_prime: i === 0 && bp === 0,
      is_three_prime: i === 1 && bp === 2, is_flexible_segment: i === 0 ? bp > 0 : bp < 2,
      backbone_position: shift(n.backbone_position), base_position: shift(n.base_position),
      slab_position: shift(n.slab_position), helical_site: { ...n.helical_site, axis_point: [i * 3, 0, bp * .34] } }
  }))
  value.helix_axes = topology.helices.map((h, i) => {
    const bp = i === 0 ? 0 : 2, position = [i * 3, 0, bp * .34]
    return { helix_id: h.id, start: position, end: position, samples: [], segments: [{
      strand_id: 's', domain_index: i, ovhg_id: null, bp_lo: bp, bp_hi: bp,
      start: position, end: position, domain_ids: [{ strand_id: 's', domain_index: i }] }] }
  })
  value.required_renderers = ['flexible-arcs']
  value.bounds_nm = { minimum: [-1, -1, -.1], maximum: [4, 1, 1] }
  return value
}
describe('private complete transform renderer', () => {
  it('renders an authored junction owned by consecutive native flexible-run beads', () => {
    const component = flexibleJunctionComponent(), original = JSON.stringify(component), scene = new THREE.Scene()
    const layer = buildTransformPreviewLayer(component, scene); owners.push(layer)
    const flexible = layer.root.getObjectByName('flexibleArcs')
    expect(flexible.getObjectByName('flexSegmentBeads').count).toBe(4)
    expect(flexible.getObjectByName('flexSegmentSlabs').count).toBe(4)
    expect(flexible.children.filter(n => n.geometry?.type === 'TubeGeometry')).toHaveLength(1)
    expect(layer.geometry.backboneEntries).toHaveLength(2)
    expect(Boolean(layer.root.getObjectByName('xoverArcMerged_transformPreview'))).toBe(false)
    expect(JSON.stringify(component)).toBe(original)
  })
  it('omits the rigid anchor-to-anchor chord already owned by the native flexible companion', () => {
    const component = flexibleJunctionComponent(); component.display_topology.forced_ligations = []
    const layer = buildTransformPreviewLayer(component, new THREE.Scene()); owners.push(layer)
    expect(layer.root.getObjectByName('flexSegmentBeads').count).toBe(4)
    expect(Boolean(layer.root.getObjectByName('xoverArcMerged_transformPreview'))).toBe(false)
  })
  it('suppresses a same-helix rigid cone across the flexible run without changing native record poses', () => {
    const component = flexibleJunctionComponent(), topology = component.display_topology
    topology.helices = [{ ...topology.helices[0], length_bp: 6, axis_end: { x: 0, y: 0, z: 1.7 } }]
    Object.assign(topology.strands[0].domains[1], { helix_id: 'a', start_bp: 3, end_bp: 5 })
    topology.cluster_transforms.forEach((c, domain_index) => {
      c.helix_ids = ['a']; c.domain_ids = [{ strand_id: 's', domain_index }]
    })
    const connection = topology.flexible_connections[0]
    for (const ref of [...topology.flexible_segment_marks, connection.anchor_a, connection.anchor_b, ...connection.segment_bead_keys])
      if (ref.domain_index === 1) ref.bp_index += 3
    topology.forced_ligations = []
    component.nucleotides = component.nucleotides.map((previous, i) => ({ ...dnaRecord(i),
      helix_id: 'a', domain_index: previous.domain_index, is_flexible_segment: previous.is_flexible_segment,
      is_five_prime: i === 0, is_three_prime: i === 5 }))
    const end = [0, 0, 1.7], lastSegment = component.helix_axes[1].segments[0]
    component.helix_axes = [{ ...component.helix_axes[0], end, segments: [component.helix_axes[0].segments[0],
      { ...lastSegment, bp_lo: 5, bp_hi: 5, start: end, end }] }]
    component.bounds_nm.maximum = [1, 1, 2]
    const original = JSON.stringify(component), layer = buildTransformPreviewLayer(component, new THREE.Scene()); owners.push(layer)
    expect(layer.root.getObjectByName('flexSegmentBeads').count).toBe(4)
    expect(layer.geometry.native.coneEntries).toHaveLength(1)
    const cone = layer.geometry.native.coneEntries[0], matrix = new THREE.Matrix4(), scale = new THREE.Vector3()
    expect(cone.isCrossHelix).toBe(false); expect(cone.coneRadius).toBeGreaterThan(0)
    cone.instMesh.getMatrixAt(cone.id, matrix); scale.setFromMatrixScale(matrix)
    expect(scale.lengthSq()).toBe(0)
    expect(layer.geometry.backboneEntries.map(e => e.pos.toArray())).toEqual([
      component.nucleotides[0].backbone_position, component.nucleotides[5].backbone_position,
    ])
    expect(JSON.stringify(component)).toBe(original)
  })
  it('does not accept an unrelated junction merely because both endpoints are flexible', () => {
    const component = flexibleJunctionComponent(), junction = component.display_topology.forced_ligations[0]
    junction.three_prime_bp = 1; junction.five_prime_bp = 1
    const scene = new THREE.Scene()
    expect(() => buildTransformPreviewLayer(component, scene)).toThrow('authored junction connection was omitted')
    expect(scene.children).toHaveLength(0)
  })
  it('requires the native flexible companion to render before crediting its junction bonds', () => {
    const component = flexibleJunctionComponent()
    component.nucleotides[0].is_flexible_segment = true // no rigid anchor: native companion must decline
    const scene = new THREE.Scene()
    expect(() => buildTransformPreviewLayer(component, scene)).toThrow('flexible segment records were omitted')
    expect(scene.children).toHaveLength(0)
  })
  it('uses native slab matrices and leaves canonical store, root and camera pose untouched', () => {
    const { scene, camera, live, light, preview } = setup(), packet = transformPacket(), original = JSON.stringify(packet)
    const position = camera.position.clone()
    vi.spyOn(store, 'getState').mockImplementation(() => { throw new Error('live store access') })
    vi.spyOn(store, 'setState').mockImplementation(() => { throw new Error('live store mutation') })
    preview.open(packet)
    expect(live.visible).toBe(true); expect(camera.layers.test(live.layers)).toBe(false)
    expect(camera.position.equals(position)).toBe(true)
    const geometry = preview.candidateGeometry()
    expect(geometry.backboneEntries).toHaveLength(2)
    const slab = geometry.slabEntries[0], matrix = new THREE.Matrix4(), center = new THREE.Vector3()
    slab.instMesh.getMatrixAt(slab.id, matrix); center.setFromMatrixPosition(matrix)
    expect(center.toArray()).toEqual(expect.arrayContaining(packet.candidate.nucleotides[0].slab_position.map(v => expect.closeTo(v, 6))))
    expect(JSON.stringify(packet)).toBe(original)
    preview.dispose(); expect(scene.children).toEqual([live, light]); expect(camera.layers.mask).toBe(1)
  })
  it('preserves last accepted candidate on malformed update and disposes partially built Open', () => {
    const { scene, live, light, preview } = setup(), bad = transformPacket(); bad.candidate.nucleotides.pop()
    expect(() => preview.open(bad)).toThrow(); expect(scene.children).toEqual([live, light])
    preview.open(transformPacket()); const previous = preview.candidateGeometry()
    expect(() => preview.replaceCandidate(bad.candidate)).toThrow()
    expect(preview.candidateGeometry()).toBe(previous)
    preview.replaceCandidate(null); expect(preview.candidateGeometry()).toBe(null)
    preview.show('before'); preview.replaceCandidate(transformComponent()); preview.show('candidate')
  })
  it('never restores a camera layer taken by a newer owner', () => {
    const { camera, preview } = setup(); preview.open(transformPacket())
    camera.layers.set(7); preview.dispose(); expect(camera.layers.mask).toBe(1 << 7)
  })
  it('releases private resources once and leaves shared geometry usable', () => {
    const scene = new THREE.Scene(), layer = buildTransformPreviewLayer(transformComponent(), scene); owners.push(layer)
    const shared = new Set(), materials = new Set()
    layer.root.traverse(node => { if (node.geometry?.userData?.shared) shared.add(node.geometry); if (node.material) materials.add(node.material) })
    const sharedSpies = [...shared].map(value => vi.spyOn(value, 'dispose'))
    const disposed = [...materials].map(value => vi.spyOn(value, 'dispose'))
    layer.dispose(); layer.dispose()
    for (const spy of sharedSpies) expect(spy).not.toHaveBeenCalled()
    for (const spy of disposed) expect(spy).toHaveBeenCalledOnce()
    expect(scene.children).toEqual([])
  })
})
