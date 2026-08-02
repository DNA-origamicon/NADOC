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

// ── Per-cluster colour + opacity ──────────────────────────────────────────────
// The surface is ONE merged mesh with one material, so material.opacity is global (the
// sidebar slider owns it) and the fade rides a per-VERTEX channel — the same
// `instanceAlpha` attribute and shader patch the instanced meshes use, because
// `attribute float instanceAlpha` is per-vertex in GLSL.
//
// Identity is per NUCLEOTIDE when the payload carries `vertex_nuc_index_table`, and per
// strand otherwise. A strand id alone cannot resolve a strand that spans clusters — the
// scaffold spans nearly all of them (LESSONS D15).

// Same two triangles, but vertices 0,1 and 2,3 are DIFFERENT NUCLEOTIDES OF ONE STRAND —
// the case a strand-keyed lookup cannot express.
const NUC_DATA = {
  ...DATA,
  vertex_strand_index_table: ['scaffold'],
  vertex_strand_index: [0, 0, 0, 0],
  vertex_nuc_index_table: ['hA:5:FORWARD', 'hB:9:FORWARD'],
  vertex_nuc_index: [0, 0, 1, 1],
}

describe('surface per-cluster colour + opacity', () => {
  const build = (data = DATA) => {
    const scene = makeScene()
    const sr = initSurfaceRenderer(scene)
    sr.setColorMode('strand')
    sr.update(data)
    return { scene, sr }
  }
  const alphaAttr = (sr) => sr.getMesh()?.geometry.getAttribute('instanceAlpha')
  const colorAt = (sr, v) => {
    const c = sr.getMesh().geometry.getAttribute('color')
    return [c.getX(v), c.getY(v), c.getZ(v)]
  }

  it('installs nothing while nothing is faded', () => {
    const { sr } = build()
    sr.applyClusterDisplay({})
    expect(alphaAttr(sr)).toBeUndefined()
  })

  it('fades ONE nucleotide of a strand without touching its neighbour', () => {
    // The regression pin. All four vertices share a strand; only two are in the faded
    // cluster, which strand-keyed resolution could not express at all.
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    const a = alphaAttr(sr)
    expect(a.getX(0)).toBeCloseTo(0.3, 5)
    expect(a.getX(1)).toBeCloseTo(0.3, 5)
    expect(a.getX(2)).toBe(1)
    expect(a.getX(3)).toBe(1)
  })

  it('colours ONE nucleotide of a strand without touching its neighbour', () => {
    const { sr } = build(NUC_DATA)
    sr.applyStrandColors(new Map([['scaffold', 0x000000]]))
    sr.applyClusterDisplay({ nucColors: new Map([['hA:5:FORWARD', 0xff0000]]) })
    expect(colorAt(sr, 0)).toEqual([1, 0, 0])          // cluster tint
    expect(colorAt(sr, 2)).toEqual([0, 0, 0])          // untouched strand colour
  })

  it('FALLS BACK to strand keys when the payload has no nucleotide table', () => {
    // An oxDNA frame-surface overlay, or a surface cached before the backend shipped
    // the block. Coarser, but it still fades rather than silently doing nothing.
    const { sr } = build(DATA)
    sr.applyClusterDisplay({
      nucAlphas: new Map([['hA:5:FORWARD', 0.3]]),
      strandAlphas: new Map([['sA', 0.4]]),
    })
    const a = alphaAttr(sr)
    expect(a.getX(0)).toBeCloseTo(0.4, 5)              // strand sA
    expect(a.getX(2)).toBe(1)                          // strand sB
  })

  it('prefers the NUCLEOTIDE table when both are supplied', () => {
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({
      nucAlphas: new Map([['hA:5:FORWARD', 0.3]]),
      strandAlphas: new Map([['scaffold', 0.9]]),
    })
    expect(alphaAttr(sr).getX(0)).toBeCloseTo(0.3, 5)
  })

  it('uses itemSize 1 — a float per vertex, not a widened colour', () => {
    const { sr } = build(NUC_DATA)
    sr.applyStrandColors(new Map([['scaffold', 0xff0000]]))
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    expect(alphaAttr(sr).itemSize).toBe(1)
    // …and the colour attribute is untouched, still RGB. Widening THAT to RGBA was the
    // alternative; a separate attribute leaves all five colour-write sites alone.
    expect(sr.getMesh().geometry.getAttribute('color').itemSize).toBe(3)
  })

  it('patches the material so the alpha blends', () => {
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    expect(sr.getMesh().material.userData.instanceAlphaPatch).toBe(true)
    expect(sr.getMesh().material.transparent).toBe(true)
  })

  it('the global slider at 1.0 does NOT switch blending off under a fade', () => {
    // setOpacity's `transparent = val < 1.0` would otherwise silently discard the
    // per-vertex fade the moment the slider reached full.
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    sr.setOpacity(1.0)
    expect(sr.getMesh().material.transparent).toBe(true)
    expect(sr.getMesh().material.opacity).toBe(1.0)
  })

  it('…and still turns blending off when nothing is faded', () => {
    const { sr } = build(NUC_DATA)
    sr.setOpacity(1.0)
    expect(sr.getMesh().material.transparent).toBe(false)
  })

  it('restores every vertex to opaque when cleared', () => {
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    sr.applyClusterDisplay({})
    const a = alphaAttr(sr)
    for (let v = 0; v < 4; v++) expect(a.getX(v)).toBe(1)
  })

  it('survives a recolour — applyStrandColors must not drop the fade', () => {
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    sr.applyStrandColors(new Map([['scaffold', 0x00ff00]]))
    expect(alphaAttr(sr).getX(0)).toBeCloseTo(0.3, 5)
  })

  it('survives a geometry rebuild', () => {
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    sr.update(NUC_DATA)
    expect(alphaAttr(sr).getX(0)).toBeCloseTo(0.3, 5)
  })

  it('leaves unlisted nucleotides opaque', () => {
    const { sr } = build(NUC_DATA)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hZ:0:FORWARD', 0.1]]) })
    const a = alphaAttr(sr)
    for (let v = 0; v < 4; v++) expect(a.getX(v)).toBe(1)
  })
})

// The extension-tail case, end to end through the renderer: a surface vertex on a
// synthetic `__ext_` helix arrives as `__ext_e5:0:FORWARD`, which no per-bp map entry
// can match — it resolves via the bare-helix fallback.
describe('surface — extension tails on synthetic helices', () => {
  const EXT_DATA = {
    ...DATA,
    vertex_strand_index_table: ['s1'],
    vertex_strand_index: [0, 0, 0, 0],
    // verts 0,1 = a real duplex nucleotide; verts 2,3 = an extension tail bead
    vertex_nuc_index_table: ['hA:5:FORWARD', '__ext_e5:0:FORWARD'],
    vertex_nuc_index: [0, 0, 1, 1],
  }
  const build = () => {
    const scene = makeScene()
    const sr = initSurfaceRenderer(scene)
    sr.setColorMode('strand')
    sr.update(EXT_DATA)
    return sr
  }

  it('fades an extension vertex via the bare-helix key', () => {
    const sr = build()
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3], ['__ext_e5', 0.3]]) })
    const a = sr.getMesh().geometry.getAttribute('instanceAlpha')
    expect(a.getX(0)).toBeCloseTo(0.3, 5)   // duplex
    expect(a.getX(2)).toBeCloseTo(0.3, 5)   // extension tail — the reported gap
  })

  it('colours an extension vertex via the bare-helix key', () => {
    const sr = build()
    sr.applyStrandColors(new Map([['s1', 0x000000]]))
    sr.applyClusterDisplay({ nucColors: new Map([['__ext_e5', 0xff0000]]) })
    const c = sr.getMesh().geometry.getAttribute('color')
    expect([c.getX(2), c.getY(2), c.getZ(2)]).toEqual([1, 0, 0])
    expect([c.getX(0), c.getY(0), c.getZ(0)]).toEqual([0, 0, 0])   // duplex untouched
  })
})

// ── Simulation-frame surfaces ────────────────────────────────────────────────
// Every engine overlay (oxDNA relaxed / RMSF / trajectory, NAMD via mdViz) reaches the
// renderer through applyPositionLerp → _rebuildTopology, NOT through update(). That path
// never recorded the payload, so `_cachedData` still described the DESIGN surface while
// the mesh on screen was a sim frame — and the cluster machinery either early-returned
// or resolved against the wrong identity table. The whole suite went through update(),
// which is why the gap was invisible.

describe('surface — simulation frames keep cluster colour + opacity', () => {
  const SIM = {
    vertices: [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0],
    faces: [0, 1, 2, 1, 3, 2],
    vertex_colors: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    vertex_strand_index_table: ['s1'],
    vertex_strand_index: [0, 0, 0, 0],
    vertex_nuc_index_table: ['hA:5:FORWARD', 'hB:9:FORWARD'],
    vertex_nuc_index: [0, 0, 1, 1],
  }
  const build = () => {
    const scene = makeScene()
    const sr = initSurfaceRenderer(scene)
    sr.setColorMode('strand')
    sr.update(DATA)                 // a design surface is on screen first, as in the app
    // …and it has been coloured, so a `color` attribute exists. The in-place lerp path
    // reuses the existing buffers, so a cluster tint has somewhere to land only if one
    // does — which is the real app's state.
    sr.applyStrandColors(new Map([['sA', 0x000000], ['sB', 0x000000]]))
    return sr
  }
  const push = (sr, data) => sr.applyPositionLerp(data, data, 0)
  const alphaAt = (sr, v) => sr.getMesh().geometry.getAttribute('instanceAlpha')?.getX(v)
  const colorAt = (sr, v) => {
    const c = sr.getMesh().geometry.getAttribute('color')
    return [c.getX(v), c.getY(v), c.getZ(v)]
  }

  it('fades a simulated surface per nucleotide', () => {
    const sr = build()
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    push(sr, SIM)
    expect(alphaAt(sr, 0)).toBeCloseTo(0.3, 5)
    expect(alphaAt(sr, 2)).toBe(1)
  })

  it('colours a simulated surface per nucleotide', () => {
    const sr = build()
    sr.applyClusterDisplay({ nucColors: new Map([['hA:5:FORWARD', 0xff0000]]) })
    push(sr, SIM)
    expect(colorAt(sr, 0)).toEqual([1, 0, 0])
    expect(colorAt(sr, 2)).toEqual([0, 0, 0])
  })

  it('applies a fade set AFTER the frame landed', () => {
    // Dragging the opacity slider while a simulation overlay is on screen.
    const sr = build()
    push(sr, SIM)
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    expect(alphaAt(sr, 0)).toBeCloseTo(0.3, 5)
  })

  it('does NOT tint a scalar (RMSF) payload — the viridis ramp is the information', () => {
    const sr = build()
    sr.applyClusterDisplay({ nucColors: new Map([['hA:5:FORWARD', 0xff0000]]) })
    push(sr, { ...SIM, scalar: true, vertex_colors: [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1] })
    expect(colorAt(sr, 0)).toEqual([0, 0, 1])      // untouched viridis
  })

  it('…but still FADES a scalar payload — opacity is never mode-gated', () => {
    const sr = build()
    sr.applyClusterDisplay({ nucAlphas: new Map([['hA:5:FORWARD', 0.3]]) })
    push(sr, { ...SIM, scalar: true })
    expect(alphaAt(sr, 0)).toBeCloseTo(0.3, 5)
  })

  it('falls back to strand keys for a frame with no nucleotide table', () => {
    const sr = build()
    sr.applyClusterDisplay({ strandAlphas: new Map([['s1', 0.4]]) })
    const { vertex_nuc_index_table, vertex_nuc_index, ...noNuc } = SIM
    push(sr, noNuc)
    expect(alphaAt(sr, 0)).toBeCloseTo(0.4, 5)
  })

  it('re-resolves against the NEW frame, not the design surface it replaced', () => {
    // The concrete failure `_cachedData` caused: identity resolved against whatever
    // update() last cached, so vertices took another mesh's cluster.
    const sr = build()
    sr.applyClusterDisplay({
      nucAlphas: new Map([['hA:5:FORWARD', 0.3]]),
      strandAlphas: new Map([['sA', 0.9]]),        // DATA's strands — must not win
    })
    push(sr, SIM)
    expect(alphaAt(sr, 0)).toBeCloseTo(0.3, 5)
  })
})
