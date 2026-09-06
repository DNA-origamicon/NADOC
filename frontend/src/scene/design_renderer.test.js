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

describe('structural partial reconciliation', () => {
  it('refreshes reference materials and completes operation timing on fast paths', () => {
    expect(SRC).toContain('_helixCtrl.setReferenceStrands(nextRefs, newState.currentDesign)')
    expect(SRC).toContain("markOperationTiming('scene-partial-patched')")
    const finishCalls = SRC.match(/finishOperationAfterRender\(\)/g) ?? []
    expect(finishCalls.length).toBeGreaterThanOrEqual(3)
  })

  it('rejects nucleotide-only patching when a moved protein changes cylinder axes', () => {
    const body = functionBody(SRC, '_tryPatchInPlace')
    expect(body).toContain('prevHelixAxes')
    expect(body).toContain('newState.currentHelixAxes')
    expect(body).toContain("reason: 'helix-axis-changed'")
  })

  it('bounds the overlay fast path and preserves a full-rebuild fallback', () => {
    const body = functionBody(SRC, '_tryStructuralOverlay')
    expect(body).not.toBeNull()
    expect(body).toContain('realIds.length > 12')
    expect(body).toContain('_sameCrossoverTopology')
    expect(body).toContain('currentDesign?.deformations')
    expect(body).toContain('_detailLevel === 1')
    expect(body).toContain('_detailLevel === 2')
    expect(body).toContain('_crossoverChangesAreLocal')
    expect(body).toContain('representation_overrides')
    expect(body).toContain('return false')
  })

  it('renders only the changed geometry and schedules authoritative consolidation', () => {
    const body = functionBody(SRC, '_tryStructuralOverlay')
    expect(body).toContain('changedSet.has(n.helix_id)')
    expect(body).toContain('buildHelixObjects')
    expect(body).toContain("markOperationTiming('structural-partial-render'")
    expect(body).toContain('requestIdleCallback')
    expect(body).toContain('_rebuild(newGeo, fullDesign')
  })

  it('disposes an overlay before every global scene rebuild', () => {
    const body = functionBody(SRC, '_rebuild')
    expect(body).toContain('_clearStructuralOverlay()')
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

  it('uses alpha visibility without rewriting live extra-base poses', () => {
    // Hidden/reference toggles are presentation state. Rebuilding matrices here
    // used to snap simulated insert beads back onto their native Bezier.
    const body = functionBody(SRC, '_applyXoverClusterAlpha')
    expect(body).toContain('const hidden =')
    expect(body).toContain('hidden || !repVisible(ad) ? 0')
    expect(functionBody(SRC, '_applyXoverVisibility')).not.toContain('setMatrixAt')
    expect(functionBody(SRC, '_applyReferenceXoverVisibility')).not.toContain('setMatrixAt')
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

describe('display-only rebuild preserves the active visualization', () => {
  // setExtraNucleotides (the oxDNA capture-strand injection) is the ONE rebuild that
  // changes no design. Everything downstream still reads it as "the design changed",
  // so without an explicit restore each surface-strand keystroke reverted the user's
  // whole visualization — structure back to NADOC native positions, flexibility map
  // back to strand colours, every halo gone.
  it('the injection rebuild is followed by the overlay restore', () => {
    // setExtraNucleotides is an object-literal method, not a `function` declaration.
    const start = SRC.indexOf('setExtraNucleotides(nucs')
    expect(start).toBeGreaterThan(-1)
    const body = SRC.slice(start, SRC.indexOf('debugCaptureRender()', start))
    const rebuild = body.indexOf('_rebuild(currentGeometry')
    const restore = body.indexOf('_restoreDisplayOverlays(this)')
    expect(rebuild).toBeGreaterThan(-1)
    expect(restore).toBeGreaterThan(rebuild)   // restore AFTER the rebuild that wiped it
  })

  it('restores every overlay the renderer itself caches', () => {
    // Each cache added here must be restored here too, or it silently reverts.
    const body = functionBody(SRC, '_restoreDisplayOverlays')
    for (const cache of ['_activeFemUpdates', '_activeScalarColors']) {
      expect(body, `${cache} is cached but never restored`).toContain(cache)
    }
  })

  it('only restores an overlay that was live on the root this rebuild replaced', () => {
    // A frame the user already dismissed with a real design edit must stay dismissed;
    // without the generation gate a later strand edit would resurrect it.
    const body = functionBody(SRC, '_restoreDisplayOverlays')
    expect(body).toContain('_rebuildSerial - 1')
    expect(body).toContain('_femSerial === live')
    expect(body).toContain('_scalarSerial === live')
  })

  it('announces the rebuild so overlay owners re-resolve their own state', () => {
    // Glow layers hold entry references into the disposed scene graph. Their owners
    // (anchor_glow, clash_overlay, selection_manager) re-resolve on this event —
    // their store subscriptions cannot fire, because the store never changed.
    expect(functionBody(SRC, '_restoreDisplayOverlays'))
      .toContain("new CustomEvent('nadoc:display-rebuilt')")
  })
})
