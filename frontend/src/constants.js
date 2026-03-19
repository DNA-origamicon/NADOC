/**
 * Frontend mirror of backend/core/constants.py B-DNA parameters.
 *
 * Used only for live-preview calculations (e.g. ghost helix in command palette).
 * Never used for rendering the actual design — that always comes from the server.
 */

export const BDNA_RISE_PER_BP       = 0.334
export const BDNA_TWIST_PER_BP      = 34.3
export const HELIX_RADIUS           = 1.0
export const HONEYCOMB_LATTICE_RADIUS = 1.125
export const HONEYCOMB_HELIX_SPACING  = 2.25
export const HONEYCOMB_COL_PITCH      = 1.125 * Math.sqrt(3)
export const HONEYCOMB_ROW_PITCH      = 2.25

export const SQUARE_HELIX_SPACING     = 2.6
