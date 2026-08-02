/**
 * impostor_material.test.js — the impostor material's shader patch, and its
 * composition with the per-instance alpha patch.
 *
 * The composition is the whole point of this file. `applyInstanceAlphaMaterial`
 * ASSIGNS `onBeforeCompile`; doing that to an impostor material would silently wipe
 * the billboard + gl_FragDepth patch and render flat camera-facing quads instead of
 * spheres. So impostors opt in through their own factory instead, and both patches
 * have to survive in one compiled program.
 */
import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  makeImpostorPhongMaterial,
  enableImpostorInstanceAlpha,
  impostorsEnabled,
} from './impostor_material.js'

/** Compile-time stand-in for the chunks both patches key off. */
const fakeShader = () => ({
  uniforms: {},
  vertexShader: '#include <common>\nvoid main() {\n#include <begin_vertex>\n#include <project_vertex>\n}\n',
  fragmentShader: '#include <common>\nvoid main() {\n#include <clipping_planes_fragment>\n' +
    '#include <color_fragment>\n#include <normal_fragment_begin>\n}\n',
})

describe('makeImpostorPhongMaterial', () => {
  it('is opt-in — impostors default OFF', () => {
    // Guards against flipping the default by accident; every gap note about
    // impostor beads leans on this being false.
    expect(impostorsEnabled()).toBe(false)
  })

  it('patches the billboard + sphere shader and binds the radius uniform', () => {
    const mat = makeImpostorPhongMaterial({ radius: 0.35 })
    const s = fakeShader()
    mat.onBeforeCompile(s)
    expect(s.uniforms.u_impostorRadius.value).toBeCloseTo(0.35)
    expect(s.vertexShader).not.toContain('#include <project_vertex>')       // replaced outright
    // The fragment patch KEEPS the clipping chunk and appends the sphere body
    // after it, so assert on the injected body rather than the chunk's absence.
    // (u_impostorRadius is declared on the VERTEX side; the fragment side gets the
    // ray-paint + depth write.)
    expect(s.vertexShader).toContain('u_impostorRadius')
    expect(s.fragmentShader).toContain('gl_FragDepth')
  })

  it('gives every material its own program cache key', () => {
    // Shared keys meant u_impostorRadius never got bound for the second material.
    const a = makeImpostorPhongMaterial({ radius: 0.1 })
    const b = makeImpostorPhongMaterial({ radius: 0.2 })
    expect(a.customProgramCacheKey()).not.toBe(b.customProgramCacheKey())
  })

  it('does NOT include the instanceAlpha patch until opted in', () => {
    // Critical: GLSL reads a missing attribute as 0, and the alpha patch discards
    // below 0.02 — patching a mesh with no instanceAlpha attribute would make every
    // bead vanish.
    const mat = makeImpostorPhongMaterial({ radius: 0.35 })
    const s = fakeShader()
    mat.onBeforeCompile(s)
    expect(s.fragmentShader).not.toContain('vInstanceAlpha')
  })
})

describe('enableImpostorInstanceAlpha', () => {
  it('composes BOTH patches into one program', () => {
    const mat = makeImpostorPhongMaterial({ radius: 0.35 })
    enableImpostorInstanceAlpha(mat)
    const s = fakeShader()
    mat.onBeforeCompile(s)
    // impostor half survives …
    expect(s.uniforms.u_impostorRadius.value).toBeCloseTo(0.35)
    expect(s.fragmentShader).toContain('gl_FragDepth')
    // … and the alpha half is present
    expect(s.fragmentShader).toContain('diffuseColor.a *= vInstanceAlpha;')
    expect(s.vertexShader).toContain('vInstanceAlpha = instanceAlpha;')
  })

  it('assigns the varying after begin_vertex, which precedes project_vertex', () => {
    // The impostor vertex patch replaces <project_vertex> and writes gl_Position
    // itself; the varying write must already have happened.
    const mat = enableImpostorInstanceAlpha(makeImpostorPhongMaterial({ radius: 0.35 }))
    const s = fakeShader()
    mat.onBeforeCompile(s)
    expect(s.vertexShader.indexOf('vInstanceAlpha = instanceAlpha;'))
      .toBeGreaterThan(s.vertexShader.indexOf('#include <begin_vertex>'))
  })

  it('marks the material transparent and keeps it depth-writing', () => {
    const mat = enableImpostorInstanceAlpha(makeImpostorPhongMaterial({ radius: 0.35 }))
    expect(mat.transparent).toBe(true)
    expect(mat.depthWrite).toBe(true)
    expect(mat.userData.photoForceDepthWrite).toBe(true)
  })

  it('is idempotent and preserves the impostor markers', () => {
    const mat = makeImpostorPhongMaterial({ radius: 0.35 })
    enableImpostorInstanceAlpha(mat)
    const v = mat.version
    enableImpostorInstanceAlpha(mat)
    expect(mat.version).toBe(v)                       // no second recompile
    expect(mat.userData.isImpostor).toBe(true)
    expect(mat.userData.impostorRadius).toBeCloseTo(0.35)
  })

  it('tolerates a null material', () => {
    expect(() => enableImpostorInstanceAlpha(null)).not.toThrow()
  })

  it('a THREE.InstancedMesh keeps its impostor material identity through opt-in', () => {
    const mat = makeImpostorPhongMaterial({ radius: 0.35 })
    const mesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), mat, 4)
    enableImpostorInstanceAlpha(mesh.material)
    expect(mesh.material.userData.isImpostor).toBe(true)
    expect(mesh.material.userData.instanceAlphaPatch).toBe(true)
  })
})
