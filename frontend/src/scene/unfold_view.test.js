/**
 * Remaining live-unfold integration/source pins. Pure merged buffer allocation,
 * RGBA channels/material and exact quadratic samples now have behavioral tests
 * in native_connection_lines.test.js; constructor-text pins were pruned after
 * extracting the shared native implementation.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { crossoverArcHiddenForRepresentations } from './view_volume_rules.js'

const SRC = readFileSync(resolve(process.cwd(), 'src/scene/unfold_view.js'), 'utf8')

describe('arc selection restoration', () => {
  it('does not repaint multi-selected crossover arcs white after a rebuild', () => {
    expect(SRC).toMatch(/if \(selected\.length === 1\)/)
    expect(SRC).not.toMatch(/selected\.has\(e\.strandId\).*0xffffff/)
  })
})

describe('remaining live arc repaint', () => {
  it('indexes the colour buffer with stride 4 everywhere, never 3', () => {
    // Every write must be `(<vert>) * 4`. A leftover `* 3` writes arc N's blue
    // channel into arc N-1's alpha.
    const strides = [...SRC.matchAll(/const ci\s*=\s*\([^)]*\)\s*\*\s*(\d)/g)].map(m => m[1])
    expect(strides.length).toBeGreaterThan(0)
    expect(strides.every(s => s === '4')).toBe(true)
  })

})

describe('arc cluster display', () => {
  it('hides a crossover when either endpoint leaves the full representation', () => {
    expect(crossoverArcHiddenForRepresentations('full', 'full')).toBe(false)
    expect(crossoverArcHiddenForRepresentations('cylinders', 'full')).toBe(true)
    expect(crossoverArcHiddenForRepresentations('full', 'surface')).toBe(true)
    expect(crossoverArcHiddenForRepresentations('stick', 'vdw')).toBe(true)
  })

  it('hides a crossover when either endpoint belongs to reference geometry', () => {
    const fn = SRC.slice(SRC.indexOf('function _reapplyArcHidden'))
    const body = fn.slice(0, SRC.indexOf('\n  function ', SRC.indexOf('function _reapplyArcHidden') + 1) - SRC.indexOf('function _reapplyArcHidden'))
    expect(body).toMatch(/refIds\.has\(e\.fromNuc\?\.strand_id\)\s*\|\|\s*refIds\.has\(e\.toNuc\?\.strand_id\)/)
    expect(body).not.toMatch(/refIds\.has\(e\.fromNuc\?\.strand_id\)\s*&&/)
  })

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
