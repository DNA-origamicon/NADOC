import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { initOxdnaInputOverlay, OXDNA_LENGTH_NM, OXDNA_VISUAL_SIZES_NM } from './oxdna_input_overlay.js'
import { BASE_COLORS, C, STAPLE_PALETTE } from './helix_renderer/palette.js'

const frames = [
  { r: [0, 0, 0], a1: [1, 0, 0], a3: [0, 0, 1], helix_id: 'h0', domain_index: 0,
    strand_id: 'cream', strand_type: 'staple', nucleobase: 'A', overhang_id: null },
  { r: [0, 0, 0.34], a1: [0, 1, 0], a3: [0, 0, 1], helix_id: 'h1', domain_index: 0,
    strand_id: 'gold', strand_type: 'staple', nucleobase: 'T', overhang_id: 'oh1' },
]
const design = {
  id: 'oxdna-overlay-test',
  strands: [{ id: 'cream', strand_type: 'staple' }, { id: 'gold', strand_type: 'staple' }],
  cluster_transforms: [{ id: 'cluster', helix_ids: ['h0'], color: '#8844cc' }],
}

function primitive(group, name) {
  return group.children.find(child => child.userData.oxdnaPrimitive === name)
}

describe('oxDNA paper-style input overlay', () => {
  it('builds every canonical primitive with oxView sizes, positions, orientation, and colors', () => {
    const scene = new THREE.Scene(), overlay = initOxdnaInputOverlay(scene)
    overlay.update(frames, [[0, 1]], 'base', design)
    const group = overlay.group()
    expect(group.userData.oxdnaInput).toBe(true)
    expect(group.children.filter(child => child.userData.oxdnaPrimitive).map(child => child.userData.oxdnaPrimitive)).toEqual([
      'backbone', 'base', 'base-connector', 'backbone-connector',
    ])
    expect(group.children.some(child => child.isLight)).toBe(false)
    const backbone = primitive(group, 'backbone'), base = primitive(group, 'base')
    const connector = primitive(group, 'base-connector'), bond = primitive(group, 'backbone-connector')
    expect([backbone.count, base.count, connector.count, bond.count]).toEqual([2, 2, 2, 1])
    for (const mesh of [backbone, base, connector, bond]) {
      expect(mesh.material.isMeshPhongMaterial).toBe(true)
      expect(mesh.material.color.getHex()).toBe(0xffffff)
      expect(mesh.material.specular.getHex()).toBe(0x333333)
      expect(mesh.material.shininess).toBe(36)
      expect(mesh.material.vertexColors).toBe(false)
      expect(mesh.geometry.getAttribute('color')).toBeUndefined()
      expect(mesh.instanceColor).not.toBeNull()
    }

    const matrix = new THREE.Matrix4(), position = new THREE.Vector3(), quaternion = new THREE.Quaternion(), scale = new THREE.Vector3()
    backbone.getMatrixAt(0, matrix); matrix.decompose(position, quaternion, scale)
    expect(position.x).toBeCloseTo(-0.34 * OXDNA_LENGTH_NM, 6)
    expect(position.y).toBeCloseTo(0.3408 * OXDNA_LENGTH_NM, 6)
    for (const value of scale.toArray()) expect(value).toBeCloseTo(OXDNA_VISUAL_SIZES_NM.backboneRadius, 6)
    base.getMatrixAt(0, matrix); matrix.decompose(position, quaternion, scale)
    expect(position.x).toBeCloseTo(0.34 * OXDNA_LENGTH_NM, 6)
    expect(scale.x).toBeCloseTo(OXDNA_VISUAL_SIZES_NM.baseRadius * 0.7, 6)
    expect(scale.y).toBeCloseTo(OXDNA_VISUAL_SIZES_NM.baseRadius * 0.3, 6)
    expect(scale.z).toBeCloseTo(OXDNA_VISUAL_SIZES_NM.baseRadius * 0.7, 6)
    expect(connector.geometry.parameters.radiusTop).toBe(1)
    expect(bond.geometry.parameters.radiusTop).toBeCloseTo(OXDNA_VISUAL_SIZES_NM.backboneConnectorTopRadius, 8)
    expect(bond.geometry.parameters.radiusBottom).toBeCloseTo(OXDNA_VISUAL_SIZES_NM.backboneConnectorBottomRadius, 8)
    const color = new THREE.Color()
    backbone.getColorAt(0, color); expect(color.getHex()).toBe(BASE_COLORS.A)
    backbone.getColorAt(1, color); expect(color.getHex()).toBe(BASE_COLORS.T)
    base.getColorAt(0, color); expect(color.getHex()).toBe(BASE_COLORS.A)
    base.getColorAt(1, color); expect(color.getHex()).toBe(BASE_COLORS.T)
  })

  it('clears and disposes the representation as a unit', () => {
    const scene = new THREE.Scene(), overlay = initOxdnaInputOverlay(scene)
    overlay.update(frames, [[0, 1]])
    expect(scene.children).toHaveLength(1)
    overlay.clear()
    expect(scene.children).toHaveLength(0)
    expect(overlay.group()).toBeNull()
  })

  it('switches live between base and strand coloring without rebuilding geometry', () => {
    const scene = new THREE.Scene(), overlay = initOxdnaInputOverlay(scene)
    overlay.update(frames, [[0, 1]], 'base', design)
    const base = primitive(overlay.group(), 'base'), first = overlay.group()
    const color = new THREE.Color()
    base.getColorAt(0, color); expect(color.getHex()).toBe(BASE_COLORS.A)
    overlay.setColoringMode('strand')
    expect(overlay.group()).toBe(first)
    base.getColorAt(0, color); expect(color.getHex()).toBe(STAPLE_PALETTE[0])
    base.getColorAt(1, color); expect(color.getHex()).toBe(STAPLE_PALETTE[1])
    overlay.setColoringMode('cluster')
    base.getColorAt(0, color); expect(color.getHex()).toBe(0x8844cc)
    base.getColorAt(1, color); expect(color.getHex()).toBe(STAPLE_PALETTE[1])
    overlay.setColoringMode('overhang-only')
    base.getColorAt(0, color); expect(color.getHex()).toBe(C.dim_gray)
    base.getColorAt(1, color); expect(color.getHex()).toBe(STAPLE_PALETTE[1])
  })
})
