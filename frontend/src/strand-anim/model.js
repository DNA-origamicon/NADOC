/**
 * Strand-animation MODEL layer — the pure, view-free core (the part meant to be
 * dropped into the main NADOC animation toolset).
 *
 * Everything reachable from here is plain math: given a parameter object + a
 * reaction coordinate φ ∈ [0,1], produce a STRAND LIST describing DNA strands
 * in the ball-and-slab convention. NO THREE.js, NO DOM, NO scene, NO backend.
 * A host imports `buildStrandGeometry` to COMPUTE geometry, then draws the
 * result with `createStrandRenderer` (strand_renderer.js) — or any renderer
 * that understands the contract below.
 *
 * ── Output contract ────────────────────────────────────────────────────────
 *   buildStrandGeometry(params, phi) -> {
 *     strands: Array<{
 *       pos: Float32Array,   // flat [x,y,z,…] backbone position per nucleotide (nm)
 *       tan: Float32Array,   // flat unit tangent     — slab "width" axis (= axis_tangent)
 *       bn:  Float32Array,   // flat unit base-normal — slab "thickness" axis (cross-strand)
 *       role: 'A' | 'B' | 'substrate' | 'invader' | 'incumbent',
 *     }>,
 *     meta: { readout: string, ...scenario-specific fields },
 *   }
 *   pos/tan/bn are length 3·count; `count` is per-strand and may differ.
 *   (tan, bn) feed scene/helix_renderer.js's slabQuaternion(bn, tan); bead
 *   positions follow backend/core/geometry.py (HELIX_RADIUS, 150° minor groove,
 *   34.3°/bp twist) — see project_strand_animations.md.
 *
 * ── Parameters ─────────────────────────────────────────────────────────────
 *   `params` is a plain object (see STRAND_DEFAULTS). The two switches that
 *   pick a builder are `scenario` ('unzip' | 'displacement') and `form`
 *   ('straight' | 'helical'). `phi` is the single reaction coordinate driving
 *   the whole animation (a host's timeline maps its 0→1 onto φ).
 */

export { DEFAULTS as STRAND_DEFAULTS } from './params.js'
export { nucsPerStrand } from './geometry_straight.js'

import { buildStraightLineGeometry } from './geometry_straight.js'
import { buildHelicalGeometry } from './geometry_helical.js'
import { buildDisplacementGeometry } from './geometry_displacement.js'

/** Role → default hex color. A renderer may override via createStrandRenderer opts. */
export const ROLE_COLOR = {
  A: 0x58a6ff,           // unzip strand A (pull up)   — blue
  B: 0xff7c7c,           // unzip strand B (pull down)  — red
  substrate: 0x8b949e,   // displacement spine          — gray
  invader: 0x3fb950,     // displacement invader        — green
  incumbent: 0xf85149,   // displacement incumbent      — red
}

/**
 * Single facade: pick the builder by scenario, then form, and return the
 * strand-list contract. This is the one model entry point a host needs.
 * @param {object} params
 * @param {number} phi  reaction coordinate ∈ [0,1]
 */
export function buildStrandGeometry(params, phi) {
  if (params.scenario === 'displacement') return buildDisplacementGeometry(params, phi)
  return params.form === 'helical'
    ? buildHelicalGeometry(params, phi)
    : buildStraightLineGeometry(params, phi)
}
