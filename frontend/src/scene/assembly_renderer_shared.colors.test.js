// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import * as helixRenderer from './helix_renderer.js'
import { _createSharedInstancingRenderer } from './assembly_renderer_shared.js'
import { C } from './helix_renderer/palette.js'

const extraMeshes = [
  'xoverExtraBeads', 'xoverExtraSlabs',
  'xoverExtraConnectors', 'xoverExtraSlabConnectors',
]

function fixture() {
  const strands = [], nucleotides = [], crossovers = []
  for (let i = 0; i < 3; i++) {
    const domains = ['a', 'b'].map((end, domain_index) => {
      const helix_id = `h${i}${end}`
      const direction = end === 'a' ? 'FORWARD' : 'REVERSE'
      const x = domain_index * 2, y = i * 3
      const overhang = i === 2 && end === 'b' ? { overhang_id: 'tip' } : {}
      nucleotides.push({ helix_id, direction, domain_index, bp_index: 0,
        strand_id: `s${i}`, strand_type: 'scaffold',
        backbone_position: [x, y, 0], base_position: [x + .5, y, 0],
        base_normal: [1, 0, 0], axis_tangent: [0, 0, 1],
        placement_source: 'native-full-o5-v1',
        slab_position: [x + .67, y, 0], slab_quaternion: [-.5, .5, .5, .5],
        ...overhang })
      return { helix_id, direction, start_bp: 0, end_bp: 0, ...overhang }
    })
    strands.push({ id: `s${i}`, strand_type: 'scaffold', sequence: 'AT', domains })
    crossovers.push({ id: `xo${i}`, extra_bases: 'GC',
      half_a: { helix_id: `h${i}a`, index: 0, strand: 'FORWARD' },
      half_b: { helix_id: `h${i}b`, index: 0, strand: 'REVERSE' } })
  }
  const design = { id: 'assembly-crossover-color-regression', helices: [], strands, crossovers,
    cluster_transforms: [
      { id: 'from', helix_ids: ['h0a'], color: '#ff2200', auto_created: false },
      { id: 'to', helix_ids: ['h0b'], color: '#0044ff', auto_created: false },
      { id: 'fallback', helix_ids: ['h1b'], color: '#22dd44', auto_created: false },
    ] }
  const assembly = { instances: [{ id: 'part',
    source: { type: 'file', path: 'color-fixture.nadoc' },
    geometrySourceKey: 'f:/color-fixture.nadoc:1:', representation: 'full', visible: true,
    transform: { values: new THREE.Matrix4().elements } }] }
  const scene = new THREE.Scene()
  const api = { getAssemblyGeometry: vi.fn(async () => ({
    instances: { part: { design, nucleotides, helix_axes: {} } },
  })) }
  const store = { getState: () => ({ currentAssembly: assembly, coloringMode: 'strand' }), subscribe: vi.fn() }
  const renderer = _createSharedInstancingRenderer({ scene, store, api })
  return { scene, renderer, assembly, api }
}

// Read the texture the actual patched material will upload, without a WebGL
// context or renderer-private source-map access.
function colorTexture(mesh) {
  const shader = { uniforms: {}, vertexShader: THREE.ShaderLib.phong.vertexShader,
    fragmentShader: THREE.ShaderLib.phong.fragmentShader }
  mesh.material.onBeforeCompile(shader)
  return shader.uniforms.u_bpColor.value
}

function expectRgb(values, offset, hex) {
  const color = new THREE.Color(hex)
  expect(values[offset]).toBeCloseTo(color.r, 6)
  expect(values[offset + 1]).toBeCloseTo(color.g, 6)
  expect(values[offset + 2]).toBeCloseTo(color.b, 6)
}

afterEach(() => vi.restoreAllMocks())

describe('shared assembly crossover color repaint', () => {
  it('preserves endpoint ownership, fallback, and overhang colors in every inserted-residue texture', async () => {
    const f = fixture()
    try {
      await f.renderer.rebuild(f.assembly)
      const meshes = extraMeshes.map(name => f.scene.getObjectByName(name))
      const textures = meshes.map(colorTexture)
      const line = f.scene.getObjectByName('instanceXoverArc_scaffold')
      expect(line.userData.arcConnections).toHaveLength(3)
      const naturalArcColors = line.geometry.getAttribute('color').array.slice()
      for (const mode of ['cluster', 'base', 'overhang-only', 'strand']) {
        f.renderer.updateColoringMode(mode)
        for (let arc = 0; arc < 3; arc++) {
          const override = mode === 'cluster'
            ? [0xff2200, 0x22dd44, null][arc]
            : mode === 'overhang-only' && arc !== 2 ? C.dim_gray : null
          for (let kind = 0; kind < meshes.length; kind++) {
            const count = kind === 2 ? 3 : 2
            const natural = kind === 1 || kind === 3 ? C.scaffold_slab : C.scaffold_backbone
            const colors = textures[kind].image.data
            for (let index = arc * count; index < (arc + 1) * count; index++) {
              expectRgb(colors, index * 4, override ?? natural)
              expect(colors[index * 4 + 3]).toBe(1)
            }
          }
          const colors = line.geometry.getAttribute('color').array
          const start = arc * 21 * 3
          for (let index = start; index < start + 21 * 3; index += 3) {
            if (override != null) expectRgb(colors, index, override)
            else expect(Array.from(colors.slice(index, index + 3)))
              .toEqual(Array.from(naturalArcColors.slice(index, index + 3)))
          }
        }
      }
    } finally { f.renderer.dispose() }
  })

  it('repaints the existing shared buffers without rebuilding nucleotide geometry or touching poses', async () => {
    const f = fixture()
    try {
      await f.renderer.rebuild(f.assembly)
      const build = vi.spyOn(helixRenderer, 'buildHelixObjects')
      const meshes = ['backboneSpheres', 'baseSlabs', ...extraMeshes]
        .map(name => f.scene.getObjectByName(name))
      const snapshots = meshes.map(mesh => ({ mesh, geometry: mesh.geometry,
        matrix: mesh.instanceMatrix, matrices: mesh.instanceMatrix.array.slice(),
        bpMatrices: mesh.userData.sharedBpXformData.slice(), texture: colorTexture(mesh) }))
      for (const mode of ['cluster', 'base', 'overhang-only', 'strand']) {
        f.renderer.updateColoringMode(mode)
      }
      expect(build).not.toHaveBeenCalled()
      expect(f.api.getAssemblyGeometry).toHaveBeenCalledOnce()
      for (const snapshot of snapshots) {
        const mesh = f.scene.getObjectByName(snapshot.mesh.name)
        expect(mesh).toBe(snapshot.mesh)
        expect(mesh.geometry).toBe(snapshot.geometry)
        expect(mesh.instanceMatrix).toBe(snapshot.matrix)
        expect(mesh.instanceMatrix.array).toEqual(snapshot.matrices)
        expect(mesh.userData.sharedBpXformData).toEqual(snapshot.bpMatrices)
        expect(colorTexture(mesh)).toBe(snapshot.texture)
        expect(mesh.instanceColor).toBeNull()
      }
    } finally { f.renderer.dispose() }
  })
})
