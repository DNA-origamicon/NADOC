import { describe, it, expect } from 'vitest'
import { initSurfaceRenderer } from './surface_renderer.js'

// Minimal scene stub — the renderer only add()/remove()s its mesh.
function makeScene() {
  const children = []
  return { add: (m) => children.push(m), remove: (m) => {
    const i = children.indexOf(m); if (i >= 0) children.splice(i, 1)
  }, children }
}

// Two triangles across a shared edge; verts 0,1 = strand A, verts 2,3 = strand B.
//   face 0 = (0,1,2) → A,A,B → majority A
//   face 1 = (1,3,2) → A,B,B → majority B
const DATA = {
  vertices: [0, 0, 0,  1, 0, 0,  0, 1, 0,  1, 1, 0],
  faces:    [0, 1, 2,  1, 3, 2],
  vertex_strand_index_table: ['sA', 'sB'],
  vertex_strand_index: [0, 0, 1, 1],
}
const MAP = new Map([['sA', 0xff0000], ['sB', 0x00ff00]])

describe('surface_renderer crisp strand zones', () => {
  it('default (blended) mode keeps indexed geometry + per-vertex colours', () => {
    const sr = initSurfaceRenderer(makeScene())
    sr.update(DATA, 'strand')
    sr.applyStrandColors(MAP)
    const geo = sr.getMesh().geometry
    expect(geo.getIndex()).not.toBeNull()                 // still indexed
    expect(geo.getAttribute('position').count).toBe(4)    // shared vertices
    // vertex 2 (strand B) is pure green — per-vertex colour, no face flattening
    const c = geo.getAttribute('color').array
    expect([c[6], c[7], c[8]]).toEqual([0, 1, 0])
  })

  it('crisp mode makes each face a single flat strand colour with sharp boundaries', () => {
    const sr = initSurfaceRenderer(makeScene())
    sr.setCrispZones(true)
    sr.update(DATA, 'strand')
    sr.applyStrandColors(MAP)
    const geo = sr.getMesh().geometry
    expect(geo.getIndex()).toBeNull()                     // non-indexed (per-face)
    expect(geo.getAttribute('position').count).toBe(6)    // 2 faces × 3 corners
    const c = geo.getAttribute('color').array
    // Face 0: all three corners red (strand A)
    expect(Array.from(c.slice(0, 9))).toEqual([1, 0, 0, 1, 0, 0, 1, 0, 0])
    // Face 1: all three corners green (strand B)
    expect(Array.from(c.slice(9, 18))).toEqual([0, 1, 0, 0, 1, 0, 0, 1, 0])
  })

  it('crisp mode keeps smooth shading (normals from the shared topology, not per-face flat)', () => {
    const sr = initSurfaceRenderer(makeScene())
    sr.setCrispZones(true)
    sr.update(DATA, 'strand')
    const nor = sr.getMesh().geometry.getAttribute('normal')
    expect(nor).toBeTruthy()
    expect(nor.count).toBe(6)
    // A planar quad in z=0 → every normal is ±z, unit length (smooth, not garbage)
    for (let i = 0; i < nor.count; i++) {
      expect(Math.abs(nor.getZ(i))).toBeCloseTo(1, 5)
    }
  })

  it('strandIdAt maps a raycast face back to its strand in crisp (non-indexed) mode', () => {
    const sr = initSurfaceRenderer(makeScene())
    sr.setCrispZones(true)
    sr.update(DATA, 'strand')
    expect(sr.strandIdAt({ a: 0 })).toBe('sA')   // face 0
    expect(sr.strandIdAt({ a: 3 })).toBe('sB')   // face 1 (corner 3 → face 1)
  })

  it('toggling crisp zones off rebuilds back to indexed geometry', () => {
    const sr = initSurfaceRenderer(makeScene())
    sr.setCrispZones(true)
    sr.update(DATA, 'strand')
    expect(sr.getMesh().geometry.getIndex()).toBeNull()
    sr.setCrispZones(false)
    expect(sr.getMesh().geometry.getIndex()).not.toBeNull()
    expect(sr.getMesh().geometry.getAttribute('position').count).toBe(4)
  })
})

// ── Per-cluster opacity ───────────────────────────────────────────────────────
// The surface is ONE merged mesh with one material, so material.opacity is global
// (the sidebar slider owns it). Per-cluster fade therefore rides a per-VERTEX
// channel, reusing the same attribute name and shader patch as the instanced
// meshes — `attribute float instanceAlpha` is per-vertex in GLSL and only becomes
// per-instance when the buffer is an InstancedBufferAttribute.

describe('surface per-cluster opacity', () => {
  const build = () => {
    const scene = makeScene()
    const sr = initSurfaceRenderer(scene)
    sr.setColorMode('strand')
    sr.update(DATA)
    return { scene, sr }
  }
  const alphaAttr = (sr) => sr.getMesh()?.geometry.getAttribute('instanceAlpha')

  it('installs nothing while nothing is faded', () => {
    const { sr } = build()
    sr.applyStrandAlphas(new Map())
    expect(alphaAttr(sr)).toBeUndefined()
  })

  it('writes a per-vertex alpha for the faded strand only', () => {
    const { sr } = build()
    sr.applyStrandAlphas(new Map([['sA', 0.3]]))
    const a = alphaAttr(sr)
    expect(a).toBeTruthy()
    // verts 0,1 = strand A; verts 2,3 = strand B
    expect(a.getX(0)).toBeCloseTo(0.3, 5)
    expect(a.getX(1)).toBeCloseTo(0.3, 5)
    expect(a.getX(2)).toBe(1)
    expect(a.getX(3)).toBe(1)
  })

  it('uses itemSize 1 — a float per vertex, not a widened colour', () => {
    const { sr } = build()
    sr.applyStrandColors(new Map([['sA', 0xff0000], ['sB', 0x00ff00]]))
    sr.applyStrandAlphas(new Map([['sA', 0.3]]))
    expect(alphaAttr(sr).itemSize).toBe(1)
    // …and the colour attribute is untouched, still RGB. Widening THAT to RGBA was
    // the alternative; a separate attribute leaves all five colour-write sites alone.
    expect(sr.getMesh().geometry.getAttribute('color').itemSize).toBe(3)
  })

  it('patches the material so the alpha blends', () => {
    const { sr } = build()
    sr.applyStrandAlphas(new Map([['sA', 0.3]]))
    expect(sr.getMesh().material.userData.instanceAlphaPatch).toBe(true)
    expect(sr.getMesh().material.transparent).toBe(true)
  })

  it('the global slider at 1.0 does NOT switch blending off under a fade', () => {
    // setOpacity's `transparent = val < 1.0` would otherwise silently discard the
    // per-vertex fade the moment the slider reached full.
    const { sr } = build()
    sr.applyStrandAlphas(new Map([['sA', 0.3]]))
    sr.setOpacity(1.0)
    expect(sr.getMesh().material.transparent).toBe(true)
    expect(sr.getMesh().material.opacity).toBe(1.0)
  })

  it('…and still turns blending off when nothing is faded', () => {
    const { sr } = build()
    sr.setOpacity(1.0)
    expect(sr.getMesh().material.transparent).toBe(false)
  })

  it('restores every vertex to opaque when cleared', () => {
    const { sr } = build()
    sr.applyStrandAlphas(new Map([['sA', 0.3]]))
    sr.applyStrandAlphas(new Map())
    const a = alphaAttr(sr)
    for (let v = 0; v < 4; v++) expect(a.getX(v)).toBe(1)
  })

  it('survives a recolour — applyStrandColors must not drop the fade', () => {
    const { sr } = build()
    sr.applyStrandAlphas(new Map([['sA', 0.3]]))
    sr.applyStrandColors(new Map([['sA', 0xff0000], ['sB', 0x00ff00]]))
    expect(alphaAttr(sr).getX(0)).toBeCloseTo(0.3, 5)
  })

  it('survives a geometry rebuild', () => {
    // _replaceMesh builds a fresh geometry that knows nothing about the fade.
    const { sr } = build()
    sr.applyStrandAlphas(new Map([['sA', 0.3]]))
    sr.update(DATA)
    expect(alphaAttr(sr).getX(0)).toBeCloseTo(0.3, 5)
  })

  it('leaves unlisted strands opaque', () => {
    const { sr } = build()
    sr.applyStrandAlphas(new Map([['nobody', 0.1]]))
    const a = alphaAttr(sr)
    for (let v = 0; v < 4; v++) expect(a.getX(v)).toBe(1)
  })
})
