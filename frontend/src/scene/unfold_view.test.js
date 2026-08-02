/**
 * unfold_view.test.js — structural pins for the crossover-arc colour buffer.
 *
 * `initUnfoldView` builds a live Three.js scene graph inside one closure and reads
 * the store, so its internals are not unit-testable without a WebGL harness — this
 * file previously had NO tests at all (`.claude/rules/unfold.md` says so).
 *
 * What IS worth pinning is the buffer contract, because it changed: arc vertex
 * colours went from RGB to RGBA so that per-cluster opacity has somewhere to live
 * (all arcs of a strand type share ONE merged LineSegments and therefore one
 * material, so a 4-component colour attribute — three's USE_COLOR_ALPHA — is the
 * only per-arc alpha channel available). A stride-3 write into an RGBA buffer does
 * not throw; it silently smears each arc's colour into its neighbour's alpha.
 * Source-text assertions are the only thing that catches that.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const SRC = readFileSync(resolve(process.cwd(), 'src/scene/unfold_view.js'), 'utf8')

describe('arc colour buffer is RGBA', () => {
  it('allocates 4 floats per vertex', () => {
    expect(SRC).toMatch(/const colors\s*=\s*new Float32Array\(vertCount \* 4\)/)
  })

  it('declares the colour attribute with itemSize 4', () => {
    // 3 here means three never defines USE_COLOR_ALPHA and the alpha is ignored —
    // the fade would silently do nothing.
    expect(SRC).toMatch(/setAttribute\('color',\s*new THREE\.BufferAttribute\(colors,\s*4\)\)/)
  })

  it('keeps positions at 3 floats per vertex', () => {
    // Guards against a copy-paste that "fixes" the position stride to match.
    expect(SRC).toMatch(/const positions\s*=\s*new Float32Array\(vertCount \* 3\)/)
    expect(SRC).toMatch(/setAttribute\('position',\s*new THREE\.BufferAttribute\(positions,\s*3\)\)/)
  })

  it('indexes the colour buffer with stride 4 everywhere, never 3', () => {
    // Every write must be `(<vert>) * 4`. A leftover `* 3` writes arc N's blue
    // channel into arc N-1's alpha.
    const strides = [...SRC.matchAll(/const ci\s*=\s*\([^)]*\)\s*\*\s*(\d)/g)].map(m => m[1])
    expect(strides.length).toBeGreaterThan(0)
    expect(strides.every(s => s === '4')).toBe(true)
  })

  it('writes all four channels at every colour-write site', () => {
    const writes = [...SRC.matchAll(/colors\[ci \+ 3\]/g)]
    // one in _buildMerged, one in _setArcColor
    expect(writes.length).toBeGreaterThanOrEqual(2)
  })

  it('keeps the material transparent — alpha < 1 is a no-op otherwise', () => {
    expect(SRC).toMatch(/new THREE\.LineBasicMaterial\(\{[^}]*vertexColors:\s*true/)
    expect(SRC).toMatch(/new THREE\.LineBasicMaterial\(\{[^}]*transparent:\s*true/)
  })
})

describe('arc cluster display', () => {
  it("_arcModeColor has a 'cluster' branch", () => {
    // Without it, arcs keep their strand colour while the helices they bridge take
    // cluster colours — the file's own comment used to say cluster "isn't wired to
    // crossovers".
    const fn = SRC.slice(SRC.indexOf('function _arcModeColor'))
    expect(fn.slice(0, 500)).toContain("mode === 'cluster'")
  })

  it('resolves an arc by fromNuc then toNuc — the same owner rule as the beads', () => {
    // design_renderer's extra-base path uses A-side-then-B-side. If these two
    // disagree, an arc and the inserted bases riding it get different clusters.
    const fn = SRC.slice(SRC.indexOf('const _arcClusterColor'))
    expect(fn.slice(0, 300)).toContain('e.fromNuc')
    expect(fn.slice(0, 300)).toContain('e.toNuc')
  })

  it('takes the LOWEST endpoint alpha, matching the overlap rule elsewhere', () => {
    const fn = SRC.slice(SRC.indexOf('function _arcAlpha'))
    expect(fn.slice(0, 400)).toContain('Math.min')
    expect(fn.slice(0, 400)).toContain('clusterAlphaForNuc')
  })

  it('defaults _setArcColor alpha to the arc’s cluster opacity', () => {
    // Selection highlight, the RMSF overlay and strand-group recolours all call
    // _setArcColor with a colour only. If the default were 1 they would each
    // silently un-fade the arc they touched.
    expect(SRC).toMatch(/function _setArcColor\(e, hex, alpha = _arcAlpha\(e\)\)/)
  })

  it('repaints on a cluster_transforms edit, not just a coloringMode change', () => {
    // Editing a swatch leaves coloringMode at 'cluster' and only mutates
    // cluster_transforms, so the coloringMode subscriber never fires for it.
    expect(SRC).toContain('clusterDisplaySignature')
  })

  it('guards that subscriber with a signature, not array identity', () => {
    // cluster_transforms is replaced on every gizmo-drag patch (~60/s) while only
    // the pose moves; identity comparison would repaint every arc every frame.
    expect(SRC).toContain('_clusterDisplaySig')
    expect(SRC).toMatch(/if \(sig === _clusterDisplaySig\) return/)
  })

  it('rebuilds the lookups after arcs are rebuilt', () => {
    // Fresh buffers know nothing about cluster styling; unconditional because a
    // fade applies in every coloring mode, including 'strand'.
    const start = SRC.indexOf('function _initArcs')
    const end = SRC.indexOf('\n  function ', start + 1)   // next sibling in the closure
    expect(start).toBeGreaterThan(-1)
    expect(SRC.slice(start, end)).toContain('_refreshClusterDisplay()')
  })

  it('exposes refreshClusterDisplay for the swatch’s live preview', () => {
    // The preview patches a design locally and never touches the store, so no
    // subscriber can see it.
    expect(SRC).toMatch(/refreshClusterDisplay\(design = null\)/)
  })
})
