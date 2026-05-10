/**
 * Pathview palette — named hex/rgba constants for the cadnano-editor canvas
 * renderer.  Extracted from pathview.js so the 4076-LOC drawing module can
 * be skimmed without scrolling past 60 lines of colour definitions.
 *
 * Values are verbatim copies — do NOT change any colour without coordinated
 * updates to backend/core/constants.py STAPLE_PALETTE and
 * frontend/src/scene/helix_renderer.js STAPLE_PALETTE (canonical palette
 * must match across all three).
 */

// ── Modification dot colours ─────────────────────────────────────────────────
// CSS hex strings matching helix_renderer.js
export const EXT_MOD_COLORS = {
  cy3: '#ff8c00', cy5: '#cc0000', fam: '#00cc00', tamra: '#cc00cc',
  bhq1: '#444444', bhq2: '#666666', atto488: '#00ffcc', atto550: '#ffaa00', biotin: '#eeeeee',
}
export const EXT_MOD_NAMES = {
  cy3: 'Cy3', cy5: 'Cy5', fam: 'FAM', tamra: 'TAMRA',
  bhq1: 'BHQ-1', bhq2: 'BHQ-2', atto488: 'ATTO488', atto550: 'ATTO550', biotin: 'Biotin',
}

// ── Background, ruler, gutter ────────────────────────────────────────────────
export const CLR_BG           = '#f0f2f5'
export const CLR_TRACK        = '#b0bac4'
export const CLR_TICK_MINOR   = '#cdd5dc'
export const CLR_TICK_MAJOR   = '#7a8fa0'
export const CLR_RULER_BG     = '#e4e8ed'
export const CLR_RULER_TEXT   = '#3a4a58'

// Gutter helix labels — forward cell = blue family, reverse cell = red family
export const CLR_LABEL_FWD_FILL   = 'rgba(41, 182, 246, 0.82)'
export const CLR_LABEL_FWD_STROKE = '#1976d2'
export const CLR_LABEL_REV_FILL   = 'rgba(239, 83, 80, 0.82)'
export const CLR_LABEL_REV_STROKE = '#c62828'
export const CLR_LABEL_TEXT       = '#ffffff'

// ── Strand / scaffold ────────────────────────────────────────────────────────
export const CLR_SCAFFOLD     = '#0070bb'
export const CLR_GHOST_SCAF   = 'rgba(0, 100, 220, 0.32)'
export const CLR_GHOST_STPL   = 'rgba(200, 60, 0, 0.32)'

// ── Slice marker ─────────────────────────────────────────────────────────────
export const CLR_SLICE_FILL   = 'rgba(245, 166, 35, 0.22)'
export const CLR_SLICE_EDGE   = '#d08800'
export const CLR_SLICE_NUM    = '#b03000'

// ── Selection ────────────────────────────────────────────────────────────────
export const CLR_SEL_RING     = '#e53935'   // selected strand highlight
export const CLR_SEL_END      = 'rgba(229, 57, 53, 0.40)'  // end-cap overlay when selected

// ── Crossover indicator — staple (non-scaffold side) ─────────────────────────
export const CLR_XOVER_FILL   = 'rgba(120, 210, 255, 0.88)'
export const CLR_XOVER_STROKE = '#1a88ee'
export const CLR_XOVER_GLOW   = 'rgba(60, 160, 255, 0.65)'
export const CLR_XOVER_TEXT   = '#0a1a2a'

// ── Crossover indicator — scaffold (scaffold side) ───────────────────────────
export const CLR_SCAF_XOVER_FILL   = 'rgba(0, 112, 187, 0.90)'
export const CLR_SCAF_XOVER_STROKE = '#004f99'
export const CLR_SCAF_XOVER_GLOW   = 'rgba(0, 80, 180, 0.60)'
export const CLR_SCAF_XOVER_TEXT   = '#cce8ff'

// ── Cell grid colours ────────────────────────────────────────────────────────
export const CLR_CELL_BG    = 'rgba(195, 208, 220, 0.38)'  // empty track cell fill
export const CLR_CELL_GRID  = '#c4cdd5'                    // minor column separator lines

// ── Canonical staple palette ─────────────────────────────────────────────────
// Must match backend/core/constants.py STAPLE_PALETTE and
// frontend/src/scene/helix_renderer.js STAPLE_PALETTE exactly.
export const STAPLE_PALETTE = [
  '#ff6b6b', '#ffd93d', '#6bcb77', '#f9844a',
  '#a29bfe', '#ff9ff3', '#00cec9', '#e17055',
  '#74b9ff', '#55efc4', '#fdcb6e', '#d63031',
]
