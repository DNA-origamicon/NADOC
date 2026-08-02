/**
 * design_renderer.test.js — structural pins for the design render pipeline.
 *
 * `initDesignRenderer` builds a live Three.js scene graph, so its 90-odd methods are not
 * unit-testable without a WebGL harness.  What IS testable — and what actually broke — is the
 * agreement between two lists that live 900 lines apart in the same closure: the glow layers
 * that get CREATED and the glow layers that get REFRESHED.
 *
 * These are source-text assertions on purpose.  A 7th glow layer was added in 2026 and nobody
 * added it to `refreshAllGlow()`, so its halo stayed pinned at the design positions while the
 * beads moved to the simulation frame.  Nothing could have caught that except comparing the
 * two lists.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// jsdom's import.meta.url is not a file: URL, so resolve from the vitest root instead.
const SRC = readFileSync(resolve(process.cwd(), 'src/scene/design_renderer.js'), 'utf8')

/** Every `const _fooGlowLayer = createGlowLayer(...)` / `createMultiColorGlowLayer(...)`. */
function createdGlowLayers(src) {
  const re = /const\s+(_\w+)\s*=\s*create(?:MultiColor)?GlowLayer\s*\(/g
  const names = []
  let m
  while ((m = re.exec(src)) !== null) names.push(m[1])
  return names
}

/** The body of the `refreshAllGlow() { ... }` method. */
function refreshAllGlowBody(src) {
  const m = src.match(/\n {4}refreshAllGlow\(\)\s*\{([\s\S]*?)\n {4}\},/)
  return m ? m[1] : null
}

describe('design_renderer glow layers', () => {
  it('creates the seven glow layers the renderer is documented to own', () => {
    expect(createdGlowLayers(SRC)).toEqual([
      '_glowLayer',
      '_undefinedGlowLayer',
      '_anchorGlowLayer',
      '_clashGlowLayer',
      '_captureGlowLayer',
      '_previewGlowLayer',
      '_fluoroGlowLayer',
    ])
  })

  it('exposes a refreshAllGlow() method', () => {
    expect(refreshAllGlowBody(SRC)).not.toBeNull()
  })

  it('refreshes EVERY created glow layer — an omitted layer lags its beads', () => {
    // refreshAllGlow() runs on every simulation frame (applyFemPositions) and every unfold /
    // expanded-spacing / cadnano reposition.  Those paths mutate `entry.pos` IN PLACE on the
    // shared backbone entries, and `refresh()` is the only thing that re-reads them.  A layer
    // left out here keeps drawing its halo at the previous positions until the next full
    // rebuild — visible as a halo detached from the strand it decorates.
    const body = refreshAllGlowBody(SRC)
    const missing = createdGlowLayers(SRC).filter(n => !body.includes(`${n}.refresh()`))
    expect(missing).toEqual([])
  })
})

// ── Cluster display (colour + opacity) ────────────────────────────────────────
// Same class of problem as the glow layers above: two things that must agree but
// live far apart in one closure. Cluster COLOUR has to be painted onto two
// different mesh families — the helix renderer's instances (via applyColoring) and
// the crossover extra-base meshes, which applyColoring never reaches because they
// live in their own InstancedMeshes. Miss the second and inserted bases keep their
// strand colour while the helices they bridge take the cluster colour.

/** Body of a named `function name(...) { ... }` in the closure, brace-matched. */
function functionBody(src, name) {
  const start = src.indexOf(`function ${name}(`)
  if (start < 0) return null
  let i = src.indexOf('{', start)
  let depth = 0
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}' && --depth === 0) return src.slice(i, j + 1)
  }
  return null
}

describe('cluster display repaint', () => {
  it('_refreshClusterDisplay repaints the extra-base meshes too, not just the helices', () => {
    const body = functionBody(SRC, '_refreshClusterDisplay')
    expect(body).not.toBeNull()
    expect(body).toContain('applyColoring')
    expect(body).toContain('_applyXoverColoring')
  })

  it('_applyXoverColoring has a cluster branch', () => {
    // Without it the mode falls through to "restore the build-time strand colour".
    const body = functionBody(SRC, '_applyXoverColoring')
    expect(body).not.toBeNull()
    expect(body).toContain("'cluster'")
    expect(body).toContain('buildClusterColorLookup')
  })

  it('both halves of _refreshClusterDisplay are independently skippable', () => {
    // Each is an O(nucleotides) sweep and the popover calls this live on every
    // pointer move, so dragging the colour map must not rebuild the alpha map and
    // dragging the opacity slider must not repaint every instance colour.
    const body = functionBody(SRC, '_refreshClusterDisplay')
    expect(body).toContain('doColor')
    expect(body).toContain('doOpacity')
    expect(body).toMatch(/if\s*\(\s*doOpacity\s*\)/)
    expect(body).toMatch(/if\s*\(\s*!doColor\s*\)\s*return/)
  })

  it('defaults to doing BOTH halves when no flags are passed', () => {
    // The store-driven path (a PATCH landing) passes nothing and must not silently
    // skip half the repaint — hence `!== false` rather than a truthiness test.
    const body = functionBody(SRC, '_refreshClusterDisplay')
    expect(body).toContain("what?.color   !== false")
    expect(body).toContain("what?.opacity !== false")
  })

  it('re-pushes cluster alphas after a rebuild, like hidden nucs and slab opacity', () => {
    // A rebuild makes fresh InstancedMeshes with fresh alpha buffers; anything that
    // persists across rebuilds has to be re-applied in that block or it silently
    // reverts on the next topology edit.
    expect(SRC).toContain('_helixCtrl.setClusterAlphas(_clusterAlphaKeys)')
  })
})

describe('crossover extra-base cluster display', () => {
  it('extra bases get their own alpha pass — setClusterAlphas cannot reach them', () => {
    // They live in separate InstancedMeshes from the helix renderer's, so an
    // inserted base stayed fully opaque inside a faded cluster.
    const body = functionBody(SRC, '_applyXoverClusterAlpha')
    expect(body).not.toBeNull()
    expect(body).toContain('installInstanceAlpha')
    expect(body).toContain('clusterAlphaForNuc')
  })

  it('installs the alpha channel LAZILY', () => {
    // installInstanceAlpha flips the material to transparent, which costs render
    // ordering and fill rate on every design — even ones with no faded cluster.
    const body = functionBody(SRC, '_applyXoverClusterAlpha')
    expect(body).toMatch(/if\s*\(!_clusterAlphaKeys\.size\s*&&\s*!_xoverBeadsMesh\._instanceAlpha\)\s*return/)
  })

  it('fades the connectors too, not just the beads and slabs', () => {
    // The arrow-cone backbone connectors thread between the inserted bases; leaving
    // them opaque would draw a solid chain through a faded cluster.
    const body = functionBody(SRC, '_applyXoverClusterAlpha')
    expect(body).toContain('_xoverConnMesh')
  })

  it('is re-applied after a rebuild and on every opacity refresh', () => {
    // A rebuild makes fresh crossover meshes with fresh (or no) alpha buffers.
    const calls = SRC.split('_applyXoverClusterAlpha()').length - 1
    expect(calls).toBeGreaterThanOrEqual(2)
    expect(functionBody(SRC, '_refreshClusterDisplay')).toContain('_applyXoverClusterAlpha()')
  })
})
