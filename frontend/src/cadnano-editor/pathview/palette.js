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

// ── Periodic-boundary seam (mirror view) ─────────────────────────────────────
export const CLR_PB_BAR       = '#dc2626'                   // slider bar (red)
export const CLR_PB_BAR_FLASH = '#ff7b7b'                   // auto-shifted bar pulse
export const CLR_PB_HANDLE    = '#dc2626'                   // grab-handle fill
export const CLR_PB_HANDLE_TXT= '#ffffff'                   // handle label text
export const CLR_PB_BAND      = 'rgba(220, 38, 38, 0.05)'   // faint tint over a mirror zone
export const CLR_PB_RULER     = '#dc2626'                   // red wrapped-bp ruler labels
export const CLR_PB_GAP_OK    = '#16a34a'                   // seam-gap readout, gap == 0
export const CLR_PB_GAP_BAD   = '#dc2626'                   // seam-gap readout, gap != 0

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

// ── Stable staple-colour resolver (shared by pathview + strands spreadsheet) ──
// A staple with no explicit colour gets a palette slot the FIRST time it is seen
// and keeps it for the life of the design. Colours used to be
// STAPLE_PALETTE[arrayIndex % 12], so a nick (adds a strand) or ligation (removes
// one) shifted every later strand's index and silently recoloured untouched
// strands — and the pathview canvas and the spreadsheet (which sorts its rows)
// disagreed. Keying on strand.id pins each colour, so only strands an op actually
// creates/removes change colour, and both views agree. Mirrors the 3D renderer's
// per-strand-id stapleColorMap. The map resets when a different design loads.
let _stapleColors = new Map()      // strandId → hex
let _stapleColorsDesignId = null

/** Pin a palette colour for every as-yet-unseen staple. Idempotent; call before
 *  reading colours (cheap — only new strand ids do work). */
export function ensureStapleColors(design) {
  if (!design) return
  if (design.id !== _stapleColorsDesignId) {
    _stapleColors = new Map()
    _stapleColorsDesignId = design.id
  }
  const strands = design.strands ?? []
  // First-encounter slot is the array index, so a design shows the exact same
  // colours on load as before; the map then pins them against later reshuffles.
  for (let i = 0; i < strands.length; i++) {
    const s = strands[i]
    if (s.strand_type === 'scaffold' || s.color) continue   // scaffold + explicit colours bypass the palette
    if (!_stapleColors.has(s.id)) _stapleColors.set(s.id, STAPLE_PALETTE[i % STAPLE_PALETTE.length])
  }
}

/** Display colour for a strand: scaffold blue, explicit colour, else its pinned
 *  palette slot. Call ensureStapleColors(design) first so the slot exists. */
export function stapleColorOf(strand) {
  if (!strand) return STAPLE_PALETTE[0]
  if (strand.strand_type === 'scaffold') return CLR_SCAFFOLD
  if (strand.color) return strand.color
  return _stapleColors.get(strand.id) ?? STAPLE_PALETTE[0]
}
