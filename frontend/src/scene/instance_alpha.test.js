import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  instanceAlphaOnBeforeCompile,
  applyInstanceAlphaMaterial,
  installInstanceAlpha,
  setInstanceAlpha,
} from './instance_alpha.js'

/** Minimal stand-in for what three hands onBeforeCompile. */
const fakeShader = () => ({
  vertexShader: 'void main() {\n#include <begin_vertex>\n}\n',
  fragmentShader: 'void main() {\n#include <color_fragment>\n}\n',
})

describe('instanceAlphaOnBeforeCompile', () => {
  it('declares the attribute and the varying on the vertex side', () => {
    const s = fakeShader()
    instanceAlphaOnBeforeCompile(s)
    expect(s.vertexShader).toContain('attribute float instanceAlpha;')
    expect(s.vertexShader).toContain('varying float vInstanceAlpha;')
  })

  it('assigns the varying AFTER begin_vertex (position must already be set)', () => {
    const s = fakeShader()
    instanceAlphaOnBeforeCompile(s)
    expect(s.vertexShader.indexOf('vInstanceAlpha = instanceAlpha;'))
      .toBeGreaterThan(s.vertexShader.indexOf('#include <begin_vertex>'))
  })

  it('multiplies diffuseColor.a AFTER color_fragment, not before', () => {
    // Ordering is the whole point: color_fragment is what sets diffuseColor, so a
    // multiply placed above it would be overwritten and the fade would vanish.
    const s = fakeShader()
    instanceAlphaOnBeforeCompile(s)
    expect(s.fragmentShader.indexOf('diffuseColor.a *= vInstanceAlpha;'))
      .toBeGreaterThan(s.fragmentShader.indexOf('#include <color_fragment>'))
  })

  it('discards near-zero alpha (this is how the hide path works)', () => {
    const s = fakeShader()
    instanceAlphaOnBeforeCompile(s)
    expect(s.fragmentShader).toContain('if ( diffuseColor.a < 0.02 ) discard;')
  })

  it('redefines no stock chunk variable — only diffuseColor.a is touched (LESSONS D5)', () => {
    const s = fakeShader()
    instanceAlphaOnBeforeCompile(s)
    expect(s.fragmentShader).not.toMatch(/(vec4|vec3|float)\s+diffuseColor/)
  })
})

describe('applyInstanceAlphaMaterial', () => {
  it('installs the shared patch and marks the material transparent', () => {
    const mat = new THREE.MeshPhongMaterial()
    const before = mat.version
    applyInstanceAlphaMaterial(mat)
    expect(mat.onBeforeCompile).toBe(instanceAlphaOnBeforeCompile)
    expect(mat.transparent).toBe(true)
    // `needsUpdate` is a write-only setter in three; the bumped version is the
    // observable "recompile me" signal it produces.
    expect(mat.version).toBeGreaterThan(before)
  })

  it('sets both userData markers', () => {
    const mat = new THREE.MeshPhongMaterial()
    applyInstanceAlphaMaterial(mat)
    // read by photo_mode.swapToFlatMaterials to re-install after the swap …
    expect(mat.userData.instanceAlphaPatch).toBe(true)
    // … and by shadow_bounds, so a faded cluster keeps casting the key shadow.
    expect(mat.userData.photoForceDepthWrite).toBe(true)
  })

  it('leaves depthWrite TRUE — one mesh holds faded AND opaque instances', () => {
    const mat = new THREE.MeshPhongMaterial()
    expect(mat.depthWrite).toBe(true)
    applyInstanceAlphaMaterial(mat)
    expect(mat.depthWrite).toBe(true)
  })

  it('is idempotent', () => {
    const mat = new THREE.MeshPhongMaterial()
    applyInstanceAlphaMaterial(mat)
    applyInstanceAlphaMaterial(mat)
    expect(mat.onBeforeCompile).toBe(instanceAlphaOnBeforeCompile)
    expect(mat.userData.instanceAlphaPatch).toBe(true)
  })

  it('preserves unrelated userData', () => {
    const mat = new THREE.MeshPhongMaterial()
    mat.userData.somethingElse = 7
    applyInstanceAlphaMaterial(mat)
    expect(mat.userData.somethingElse).toBe(7)
  })

  it('tolerates a null material', () => {
    expect(() => applyInstanceAlphaMaterial(null)).not.toThrow()
  })

  // The reason the patch is a module-level named function: three derives the
  // program cache key from onBeforeCompile.toString(). Refactoring this into a
  // per-material closure would compile one shader per mesh instead of one shared.
  it('gives every patched material the SAME program cache key', () => {
    const a = applyInstanceAlphaMaterial(new THREE.MeshPhongMaterial())
    const b = applyInstanceAlphaMaterial(new THREE.MeshPhongMaterial())
    expect(a.customProgramCacheKey()).toBe(b.customProgramCacheKey())
  })

  it('gives an UNpatched material a different key (no shader leakage either way)', () => {
    const patched = applyInstanceAlphaMaterial(new THREE.MeshPhongMaterial())
    const plain = new THREE.MeshPhongMaterial()
    expect(patched.customProgramCacheKey()).not.toBe(plain.customProgramCacheKey())
  })
})

describe('installInstanceAlpha', () => {
  const mesh = (count = 4) => new THREE.InstancedMesh(
    new THREE.BoxGeometry(1, 1, 1), new THREE.MeshPhongMaterial(), count)

  it('adds an instanceAlpha attribute sized to the instance count, defaulting opaque', () => {
    const m = mesh(5)
    installInstanceAlpha(m)
    const attr = m.geometry.getAttribute('instanceAlpha')
    expect(attr.count).toBe(5)
    expect([...attr.array]).toEqual([1, 1, 1, 1, 1])
  })

  it('CLONES the geometry — the GEO_* templates are shared between meshes', () => {
    // Without the clone, installing on one mesh leaks the attribute into every
    // other mesh built from the same template.
    const shared = new THREE.BoxGeometry(1, 1, 1)
    const a = new THREE.InstancedMesh(shared, new THREE.MeshPhongMaterial(), 4)
    const b = new THREE.InstancedMesh(shared, new THREE.MeshPhongMaterial(), 4)
    installInstanceAlpha(a)
    expect(a.geometry).not.toBe(shared)
    expect(b.geometry.getAttribute('instanceAlpha')).toBeUndefined()
  })

  it('patches the material so photo mode can re-install it later', () => {
    const m = mesh()
    installInstanceAlpha(m)
    expect(m.material.onBeforeCompile).toBe(instanceAlphaOnBeforeCompile)
    expect(m.material.userData.instanceAlphaPatch).toBe(true)
  })

  it('is idempotent and does not re-clone', () => {
    const m = mesh()
    installInstanceAlpha(m)
    const geo = m.geometry
    installInstanceAlpha(m)
    expect(m.geometry).toBe(geo)
  })

  it('tolerates a null mesh', () => {
    expect(() => installInstanceAlpha(null)).not.toThrow()
  })
})

describe('setInstanceAlpha', () => {
  it('writes one instance and flags the attribute for upload', () => {
    const m = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshPhongMaterial(), 4)
    installInstanceAlpha(m)
    const attr = m.geometry.getAttribute('instanceAlpha')
    const before = attr.version
    setInstanceAlpha(m, 2, 0.35)
    expect(attr.getX(2)).toBeCloseTo(0.35)
    expect(attr.getX(0)).toBe(1)
    // `needsUpdate` is a write-only setter on BufferAttribute too; the bumped
    // version is the observable "re-upload me" signal.
    expect(attr.version).toBeGreaterThan(before)
  })

  it('is a silent no-op on a mesh with no alpha channel', () => {
    // Callers write alpha unconditionally; installation is lazy.
    const m = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshPhongMaterial(), 4)
    expect(() => setInstanceAlpha(m, 0, 0.5)).not.toThrow()
    expect(() => setInstanceAlpha(null, 0, 0.5)).not.toThrow()
  })
})
