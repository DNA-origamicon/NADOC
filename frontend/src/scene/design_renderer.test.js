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
