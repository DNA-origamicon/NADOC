/**
 * Right-sidebar "Overhang Connections" section (factory).
 *
 * A compact re-housing of the Overhangs Manager's connection-type picker +
 * linker-create flow:
 *   - two dropdowns listing every overhang in the current design (Side A / B),
 *   - the connection-type icon button (all 12 variants) opening a popover,
 *   - the icon updates live from the two selected overhangs' 5'/3' ends —
 *     polarity markers + the yellow ⚠ "forbidden pairing" overlay,
 *   - a linker-length field (hidden for direct + indirect variants),
 *   - a Generate button: "Generate Linker" (creates an OverhangConnection) for
 *     linker/indirect variants, "Make complementary" (RC-syncs B + creates an
 *     OverhangBinding) for the two direct variants,
 *   - an interactive list of created linkers + bindings (click a linker row to
 *     re-select its overhangs + type; × to delete),
 *   - while OPEN, a cyan (A) / magenta (B) additive glow over the beads of the
 *     overhang in each dropdown (matching the dropdown border colours), via two
 *     injected `createGlowLayer` overlays — cleared when the section collapses.
 *
 * Rendering + polarity rules + variant→backend mapping are reused from the
 * shared `ct_icons.js` (the same library the assembly manager uses), so there's
 * one source of truth. Backend mutations sync the design back into the store,
 * which fires this module's subscriber → the list + dropdowns refresh.
 *
 * DOM contract (ids in index.html #overhang-connections-section):
 *   #oconn-select-a, #oconn-select-b  — <select> overhang dropdowns
 *   #oconn-button-box                 — .ct-button-box (icon), opens the popover
 *   #oconn-popover                    — .ct-popover (filled with .ct-option tiles)
 *   #oconn-length-row, #oconn-length  — linker-length field (+ its wrapper)
 *   #oconn-generate                   — Generate Linker / Make complementary
 *   #oconn-list                       — interactive linker/binding list
 */

import {
  CT_VARIANTS, ctTileSvg, ctIsForbidden, ctForbiddenReason, endOf,
  ctAttachPair, ctIsDirect, ctIsIndirect, ctLinkerType, ctVariantForConnection,
} from './ct_icons.js'
import {
  createOverhangConnection, deleteOverhangConnection, patchOverhangConnection,
  createOverhangBinding, deleteOverhangBinding, patchOverhangBinding, patchOverhang,
  generateRandomSequence, generateOverhangRandomSequence, relaxLinker,
  relaxOverhangBinding,
  createConnectionVersion, createAndApplyConnectionVersion,
  patchConnectionVersion, deleteConnectionVersion,
  applyConnectionVersion, patchDuplex, relaxDuplex,
} from '../api/client.js'
import { showToast } from './toast.js'
import { showConfirm } from './primitives/confirm.js'
import { runOverhangGen } from './overhang_gen.js'
import {
  assembleOverhangSequence, overhangDomainLength, pairingSegments,
  overhangHasDuplex, overhangDuplexSegments, capSequenceToLength, overhangRcOfPartner,
} from '../scene/design_queries.js'
import { selectedOverhangIds } from '../scene/selection_model.js'

const _STORAGE = 'nadoc.overhangConnections.connectionType'

// LEFT / RIGHT dropdown highlight colors — match the neon strand colors inside
// the icon so the visual link between dropdown side and icon side is immediate.
const _NEON_A = '#00e1ff'
const _NEON_B = '#ff36c6'
// Bridge-portion colours in the sequence display (match the icon + the
// `_makeDsLinkerMeshes` red/green ds halves; white for an ss bridge).
const _LINKER_BRIDGE_COLOR = '#ffffff'
const _LINKER_DS_A_COLOR   = '#dc3545'
const _LINKER_DS_B_COLOR   = '#27ae60'

// Per-base pairing colors for the sequence previews: which bases actually
// hybridize (complementary) vs are excess/unpaired. Anchored at the bound /
// attach sub-domain (see `pairingSegments`).
const _PAIR_COLOR = {
  paired:   '#3fb950',   // Watson-Crick complementary → forms the duplex
  unpaired: '#d29922',   // inside the bound region but a mismatch / N → won't pair
  excess:   '#8b949e',   // outside the bound region: length beyond partner / undefined N tail
}
// Simple preview (no pairing context): defined bases neutral, undefined N greyed.
const _SEQ_DEFINED_COLOR   = '#c9d1d9'
const _SEQ_UNDEFINED_COLOR = '#8b949e'
// Duplex-graph coverage colors (Phase 2): read from the STORED register rather
// than the attach-anchored heuristic. Toehold = uncovered (unpaired) bases.
const _DUPLEX_COLOR = { paired: '#3fb950', mismatch: '#d29922', toehold: '#8b949e' }

let _store   = null
let _inited  = false
let _typeId  = 'end-to-root'
// Scene-highlight deps (injected; absent in unit tests → highlight no-ops).
let _designRenderer = null
let _glowA = null   // cyan glow over overhang A's beads
let _glowB = null   // magenta glow over overhang B's beads
let _selA    = null   // overhang id chosen in dropdown A (or null)
let _selB    = null   // overhang id chosen in dropdown B (or null)
let _selRow  = null   // selected list row: { kind:'version'|'conn'|'binding', id } | null
let _detailsEl = null
let _collapsedGroups = new Set()   // pairKeys whose version sublist is collapsed

// Auto-populate tracker — fed by the user's 3D scene selection (overhang filter
// OR domain filter; lasso / ctrl-shift / sequential all land in the same store
// fields). The two dropdowns behave as a 2-slot LRU: a new pick fills an empty
// slot first, else evicts whichever slot was populated LESS recently. Recency is
// a monotonic counter per slot (0 = empty).
let _slotTA = 0       // recency stamp for slot A (_selA)
let _slotTB = 0       // recency stamp for slot B (_selB)
let _clock  = 0
let _selPrev = []     // previous merged overhang-selection snapshot (for diffing)

let _selectA = null
let _selectB = null
let _box     = null
let _popover = null
let _heading = null
let _arrow   = null
let _body    = null
let _lengthRow = null
let _lengthInput = null
let _genBtn  = null        // "Connect" (new pair) / "Add version" (existing pair)
let _applyBtn = null       // "Apply" — materialize the selected version
let _secondaryBtn = null   // "Bind" (direct) / "Relax" (linker)
let _list    = null
let _seqRowA = null, _seqInputA = null, _seqGenA = null
let _seqRowB = null, _seqInputB = null, _seqGenB = null
let _seqPrevA = null, _seqPrevB = null   // colored preview lines under each seq row
let _driverBox = null                    // driver toggle (Q4), shown when a duplex joins the pair
let _pairWarnEl = null
let _collapsed = true   // default collapsed, matching sibling sidebar sections

export function initOverhangConnectionsPanel({
  store, scene = null, designRenderer = null, createGlowLayer = null,
}) {
  if (_inited) return _api
  _store = store
  _designRenderer = designRenderer
  // Two additive glow overlays (cyan = A, magenta = B) that highlight the beads
  // of the overhang in each dropdown. Separate draw calls — they never touch
  // bead colours, so they don't fight the selection system's colour tracking.
  if (scene && createGlowLayer) {
    _glowA = createGlowLayer(scene, 0x00e1ff, 3, 'oconnGlowA')
    _glowB = createGlowLayer(scene, 0xff36c6, 3, 'oconnGlowB')
  }

  _selectA = document.getElementById('oconn-select-a')
  _selectB = document.getElementById('oconn-select-b')
  _box     = document.getElementById('oconn-button-box')
  _popover = document.getElementById('oconn-popover')
  _heading = document.getElementById('oconn-heading')
  _arrow   = document.getElementById('oconn-arrow')
  _body    = document.getElementById('oconn-body')
  _lengthRow   = document.getElementById('oconn-length-row')
  _lengthInput = document.getElementById('oconn-length')
  _genBtn      = document.getElementById('oconn-generate')
  _applyBtn    = document.getElementById('oconn-apply')
  _secondaryBtn = document.getElementById('oconn-secondary')
  _list        = document.getElementById('oconn-list')
  _detailsEl   = document.getElementById('oconn-details')
  _seqRowA = document.getElementById('oconn-seq-row-a')
  _seqInputA = document.getElementById('oconn-seq-input-a')
  _seqGenA = document.getElementById('oconn-seq-gen-a')
  _seqRowB = document.getElementById('oconn-seq-row-b')
  _seqInputB = document.getElementById('oconn-seq-input-b')
  _seqGenB = document.getElementById('oconn-seq-gen-b')
  _pairWarnEl = document.getElementById('oconn-pair-warning')
  if (!_selectA || !_selectB || !_box || !_popover) return _api  // section absent

  try {
    const saved = localStorage.getItem(_STORAGE)
    if (saved && CT_VARIANTS.some(v => v.id === saved)) _typeId = saved
  } catch { /* ignore */ }

  // Collapsible section header (mirrors the sibling right-sidebar panels).
  if (_heading && _body) {
    _applyCollapse()
    _heading.addEventListener('click', () => { _collapsed = !_collapsed; _applyCollapse() })
  }

  _selectA.style.borderLeft = `3px solid ${_NEON_A}`
  _selectB.style.borderLeft = `3px solid ${_NEON_B}`

  _selectA.addEventListener('change', () => {
    _selA = _selectA.value || null
    _slotTA = _selA ? ++_clock : 0
    _selRow = null
    _render()
  })
  _selectB.addEventListener('change', () => {
    _selB = _selectB.value || null
    _slotTB = _selB ? ++_clock : 0
    _selRow = null
    _render()
  })

  _box.addEventListener('click', (ev) => {
    ev.stopPropagation()
    _popover.hidden ? _openPopover() : _closePopover()
  })

  _genBtn?.addEventListener('click', (ev) => {
    ev.stopPropagation()
    if (!_genBtn.disabled) _onPrimary()
  })

  _applyBtn?.addEventListener('click', (ev) => {
    ev.stopPropagation()
    if (!_applyBtn.disabled) _onApply()
  })

  _secondaryBtn?.addEventListener('click', (ev) => {
    ev.stopPropagation()
    if (!_secondaryBtn.disabled) _onSecondary()
  })

  _wireSeqRow('A', _seqInputA, _seqGenA)
  _wireSeqRow('B', _seqInputB, _seqGenB)

  _buildPopover()

  // Close the popover on any outside click.
  document.addEventListener('click', (ev) => {
    if (_popover.hidden) return
    if (ev.target === _box || _box.contains(ev.target) ||
        ev.target === _popover || _popover.contains(ev.target)) return
    _closePopover()
  })

  // React to design changes (load / edit / overhang add-remove): repopulate the
  // dropdowns (dropping any now-stale selection) and re-render the icon.
  _store.subscribe((s, p) => {
    if (s.currentDesign !== p.currentDesign) _refresh()
    else if (s.currentGeometry !== p.currentGeometry) _updateGlow()   // beads moved/rebuilt
  })

  // React to canonical overhang selection: when the section is open, the last two
  // selected overhang refs auto-populate the A / B dropdowns.
  _store.subscribe((s, p) => {
    if (s.selection !== p.selection) {
      _onSelectionChange(s)
    }
  })

  _refresh()
  _onSelectionChange(_store.getState())   // seed slots from any existing selection
  _inited = true
  return _api
}

// ── Internal ──────────────────────────────────────────────────────────────────

function _design() {
  return _store?.getState()?.currentDesign ?? null
}

/** Live overhangs of the current design (ghost-filtered, mirroring the manager:
 *  hide overhangs whose backing strand was deleted but spec not cascaded). */
function _overhangs() {
  const design = _design()
  if (!design) return []
  const liveStrandIds = new Set((design.strands ?? []).map(s => s.id))
  return (design.overhangs ?? []).filter(o => !o.strand_id || liveStrandIds.has(o.strand_id))
}

function _displayName(ovhg) {
  if (!ovhg) return ''
  return ovhg.label || ovhg.name || ovhg.id
}

/** Full rebuild: repopulate both dropdowns + re-render the icon. */
function _refresh() {
  const ovhgs = _overhangs()
  const ids = new Set(ovhgs.map(o => o.id))
  if (_selA && !ids.has(_selA)) { _selA = null; _slotTA = 0 }
  if (_selB && !ids.has(_selB)) { _selB = null; _slotTB = 0 }
  if (_selRow) {
    const pool = _selRow.kind === 'version' ? _versions()
               : _selRow.kind === 'conn'    ? _connections()
               : _bindings()
    if (!pool.some(e => e.id === _selRow.id)) _selRow = null
  }
  _populate(_selectA, ovhgs, _selA)
  _populate(_selectB, ovhgs, _selB)
  _render()
}

function _connections() { return _design()?.overhang_connections ?? [] }
function _bindings()    { return _design()?.overhang_bindings ?? [] }

function _populate(select, ovhgs, selectedId) {
  select.innerHTML = ''
  const blank = document.createElement('option')
  blank.value = ''
  blank.textContent = ovhgs.length ? '— select overhang —' : '(no overhangs)'
  select.appendChild(blank)
  for (const o of ovhgs) {
    const opt = document.createElement('option')
    opt.value = o.id
    const tag = endOf(o.id)
    opt.textContent = tag ? `${_displayName(o)}  (${tag === '5p' ? "5'" : "3'"})` : _displayName(o)
    select.appendChild(opt)
  }
  select.value = selectedId ?? ''
}

/** Re-render the button-box icon from the current type + selection polarities. */
function _render() {
  if (!_box) return
  const L = endOf(_selA)
  const R = endOf(_selB)
  const hasA = _selA != null
  const hasB = _selB != null
  const forbidden = hasA && hasB && ctIsForbidden(_typeId, L, R)
  _box.innerHTML = `<div class="ct-tile">${ctTileSvg(_typeId, L, R, forbidden, hasA, hasB)}</div>`
  const variant = CT_VARIANTS.find(v => v.id === _typeId)
  _box.title = ctForbiddenReason(_typeId, L, R) ?? (variant ? variant.label : '')
  _refreshPopoverTiles()
  _updateControls()
  _renderList()
  _renderDetails()
  _updateGlow()
}

/** Position the cyan (A) / magenta (B) glow over the beads of the overhang in
 *  each dropdown. Cleared while the section is collapsed (highlight is only
 *  active when the section is open). Re-fetches entries each call so it tracks
 *  rebuilds / position overlays. No-op when the glow deps weren't injected. */
function _updateGlow() {
  if (!_glowA || !_glowB) return
  if (_collapsed) { _glowA.clear(); _glowB.clear(); return }
  const entries = _designRenderer?.getBackboneEntries?.() ?? []
  _glowA.setEntries(_selA ? entries.filter(e => e?.nuc?.overhang_id === _selA) : [])
  _glowB.setEntries(_selB ? entries.filter(e => e?.nuc?.overhang_id === _selB) : [])
}

// ── Create controls (per-side sequence + length + Generate/Pair) ──────────────

/** Sync the per-side sequence rows, length-row visibility, pairing warning, and
 *  the action button's label/enabled state to the current variant + selection. */
function _updateControls() {
  const direct   = ctIsDirect(_typeId)
  const indirect = ctIsIndirect(_typeId)
  // Length only applies to real linker variants (not direct, not indirect).
  if (_lengthRow) _lengthRow.style.display = (direct || indirect) ? 'none' : ''
  _refreshSeqRows()
  _refreshSeqPreviews()
  _renderDriverToggle()
  _refreshPairWarning()
  const hasBoth   = _selA != null && _selB != null
  const forbidden = hasBoth && ctIsForbidden(_typeId, endOf(_selA), endOf(_selB))
  const existing  = hasBoth && _pairHasConnection()
  if (_genBtn) {
    _genBtn.textContent = existing ? 'Add version' : 'Connect'
    _genBtn.disabled = !hasBoth || forbidden
    _genBtn.title = !hasBoth
      ? 'Select an overhang on each side first'
      : forbidden
        ? "This polarity combination isn't valid for the selected connection type"
        : existing
          ? 'Add another candidate version for this overhang pair'
          : (direct ? 'Pair the two overhangs (create the connection)'
                    : 'Create the linker between the two overhangs')
  }
  // Apply / Unapply the target version (selected, else the pair's applied one).
  // Apply is live for BOTH direct types: it creates one non-consuming, relocated
  // OverhangBinding (the duplex forms; the driven overhang's embedded-strand bond
  // is left stretched). The only per-type difference is the attach/connection point.
  if (_applyBtn) {
    const v = _applyTargetVersion()
    if (v?.applied) {
      _applyBtn.textContent = 'Unapply'
      _applyBtn.disabled = false
      _applyBtn.title = 'Tear down this connection — leave the overhangs free'
    } else {
      _applyBtn.textContent = 'Apply'
      _applyBtn.disabled = !v
      _applyBtn.title = v
        ? "Materialize this version (replaces the pair's current connection)"
        : 'Select a version from the list to apply it'
    }
  }
  // Secondary "Relax": settle the connection's geometry. For a LINKER that's the
  // joint optimization; for a DIRECT binding (root-to-root OR end-to-root) it's the
  // unified swing-about-driver-root + cluster move that closes the driven overhang's
  // stretched tip↔root bond. Enabled when the pair has a linker, a legacy binding,
  // OR a bound duplex (the Proposal-B path for a binding-less direct connection).
  if (_secondaryBtn) {
    const c = _linkerForPair()
    const b = c ? null : _bindingForPair()
    const dx = (c || b) ? null : _boundDuplexForPair()
    _secondaryBtn.textContent = 'Relax'
    _secondaryBtn.disabled = !c && !b && !dx
    _secondaryBtn.title = c
      ? 'Relax this linker (optimize the joint so the connector collapses)'
      : (b || dx)
        ? 'Relax: swing the duplex + move the clusters together so the embedded-strand bond closes'
        : 'Apply a connection first, then relax it'
  }
}

/** The version the Apply/Unapply button acts on: the selected version if one is
 *  selected, otherwise the pair's currently-applied version ("current"). */
function _applyTargetVersion() {
  if (_selRow?.kind === 'version') return _versions().find(x => x.id === _selRow.id) ?? null
  return _versionsForPair(_selA, _selB).find(v => v.applied) ?? null
}

/** The OverhangBinding (if any) joining the current A/B pair, either order. */
function _bindingForPair() {
  if (!_selA || !_selB) return null
  return _bindings().find(b =>
    (b.overhang_a_id === _selA && b.overhang_b_id === _selB) ||
    (b.overhang_a_id === _selB && b.overhang_b_id === _selA)) ?? null
}

/** The OverhangConnection (linker, if any) joining the current A/B pair. */
function _linkerForPair() {
  if (!_selA || !_selB) return null
  return _connections().find(c =>
    (c.overhang_a_id === _selA && c.overhang_b_id === _selB) ||
    (c.overhang_a_id === _selB && c.overhang_b_id === _selA)) ?? null
}

/** The BOUND duplex (if any) joining the current pair with NO legacy binding — the
 *  Proposal-B direct connection (e.g. a different-length r2r pair relocated by
 *  `connect_duplex`). Only bound duplexes are relaxable (the driven overhang must
 *  already be relocated onto the driver's helix). */
function _boundDuplexForPair() {
  const dx = _duplexForPair()
  return dx && dx.bound ? dx : null
}

/** Secondary "Relax" action: settle the connection's geometry.
 *   - Linker → relaxLinker (optimize the joint so the connector arcs collapse).
 *   - Direct binding (root-to-root OR end-to-root) → relaxOverhangBinding: the
 *     unified server-side solve swings the driver's overhang duplex about its root
 *     (the driven tip co-rotates) + cluster kinematics so the driven overhang's
 *     stretched tip↔root bond closes to one backbone bond. The binding stays bound
 *     (no unbind/rebind dance — apply already relocated it).
 *   - Bound duplex with NO binding (Proposal-B direct connection) → relaxDuplex:
 *     the SAME solve, driver/driven resolved from the duplex. */
async function _onSecondary() {
  const c = _linkerForPair()
  const b = c ? null : _bindingForPair()
  const dx = (c || b) ? null : _boundDuplexForPair()
  if (!c && !b && !dx) return
  if (_secondaryBtn) _secondaryBtn.disabled = true
  try {
    if (c) await relaxLinker(c.id)
    else if (b) await relaxOverhangBinding(b.id)
    else await relaxDuplex(dx.id)
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _render()
  }
}

/** Show each side's sequence row (only when that side has a selection) and pull
 *  the overhang's current sequence into the input (skipping a focused input). */
function _refreshSeqRows() {
  for (const [row, input, id] of [[_seqRowA, _seqInputA, _selA], [_seqRowB, _seqInputB, _selB]]) {
    if (!row || !input) continue
    const ovhg = id ? _overhangs().find(o => o.id === id) : null
    if (!ovhg) { row.hidden = true; continue }
    row.hidden = false
    if (document.activeElement === input) continue   // don't clobber active typing
    const len = (ovhg.sub_domains ?? []).reduce((s, sd) => s + (sd.length_bp ?? 0), 0)
    input.value = ovhg.sequence ?? ''
    input.placeholder = ovhg.sequence ? '' : (len ? `N×${len}` : 'sequence…')
  }
}

/** Colored preview line under each per-side sequence input. For a DIRECT type
 *  with both sides chosen it shows which bases hybridize (green) vs are excess /
 *  unpaired (grey / amber), anchored at the attach sub-domain; otherwise it just
 *  greys the undefined N bases of whichever side is selected. Undefined bases
 *  appear as N because `_overhangBases` pads to the current backing-domain
 *  length — so a dragged-longer overhang no longer looks fully defined. */
function _refreshSeqPreviews() {
  if (_seqRowA && !_seqPrevA) { _seqPrevA = _mkPreviewBox(); _seqRowA.insertAdjacentElement('afterend', _seqPrevA) }
  if (_seqRowB && !_seqPrevB) { _seqPrevB = _mkPreviewBox(); _seqRowB.insertAdjacentElement('afterend', _seqPrevB) }
  if (_seqPrevA) { _seqPrevA.innerHTML = ''; _seqPrevA.hidden = !_seqRowA || _seqRowA.hidden }
  if (_seqPrevB) { _seqPrevB.innerHTML = ''; _seqPrevB.hidden = !_seqRowB || _seqRowB.hidden }

  const aOv = _selA ? _overhangs().find(o => o.id === _selA) : null
  const bOv = _selB ? _overhangs().find(o => o.id === _selB) : null
  const design = _design()

  // Prefer the STORED duplex register (Phase 2 — reads the graph): if either side
  // participates in a duplex, colour its bases by coverage (paired / mismatch /
  // toehold), which handles multivalency + different-length overhangs natively.
  const aDx = aOv && overhangHasDuplex(design, _selA)
  const bDx = bOv && overhangHasDuplex(design, _selB)
  if (aDx || bDx) {
    if (_seqPrevA && aOv) _seqPrevA.appendChild(_duplexLineEl(_displayName(aOv), design, _selA))
    if (_seqPrevB && bOv) _seqPrevB.appendChild(_duplexLineEl(_displayName(bOv), design, _selB))
    return
  }

  if (ctIsDirect(_typeId) && aOv && bOv) {
    const [aLine, bLine] = _pairingLineEls({ aId: _selA, bId: _selB, type: _typeId })
    if (_seqPrevA && aLine) _seqPrevA.appendChild(aLine)
    if (_seqPrevB && bLine) _seqPrevB.appendChild(bLine)
    return
  }
  if (_seqPrevA && aOv) _seqPrevA.appendChild(_simpleSeqLineEl(null, aOv))
  if (_seqPrevB && bOv) _seqPrevB.appendChild(_simpleSeqLineEl(null, bOv))
}

/** A colored preview line for one overhang, read from its DUPLEX coverage
 *  (green paired / amber mismatch / grey toehold). The driver side (Q4) is
 *  marked with a ▶. */
function _duplexLineEl(label, design, overhangId) {
  const segs = overhangDuplexSegments(design, overhangId)
    .map(s => ({ text: s.text, color: _DUPLEX_COLOR[s.kind] ?? _SEQ_DEFINED_COLOR }))
  const dx = _duplexForOverhang(design, overhangId)
  const lbl = (dx && _driverOverhangId(dx) === overhangId) ? `▶ ${label}` : label
  return _seqLineEl(lbl, segs)
}

/** The duplex-graph driver overhang id (Q4). */
function _driverOverhangId(dx) {
  return dx.driver === 'right' ? dx.right.overhang_id : dx.left.overhang_id
}

function _duplexForOverhang(design, overhangId) {
  return (design?.duplexes ?? []).find(
    d => d.left.overhang_id === overhangId || d.right.overhang_id === overhangId) ?? null
}

/** The duplex (if any) joining the current A/B pair, either order. */
function _duplexForPair() {
  if (!_selA || !_selB) return null
  return (_design()?.duplexes ?? []).find(dx => {
    const ids = new Set([dx.left.overhang_id, dx.right.overhang_id])
    return ids.has(_selA) && ids.has(_selB)
  }) ?? null
}

/** Driver toggle (Q4): two buttons letting the user pick which overhang's helix
 *  hosts the duplex, overriding the longest-drives default. Rendered into
 *  `_driverBox` when a duplex joins the current pair. */
function _renderDriverToggle() {
  if (_seqRowB && !_driverBox) {
    _driverBox = document.createElement('div')
    _driverBox.className = 'oconn-driver-box'
    _driverBox.style.cssText = 'margin:2px 0 6px 2px;display:flex;gap:6px;align-items:center'
    ;(_seqPrevB ?? _seqRowB).insertAdjacentElement('afterend', _driverBox)
  }
  if (!_driverBox) return
  _driverBox.innerHTML = ''
  const dx = _duplexForPair()
  if (!dx) { _driverBox.hidden = true; return }
  _driverBox.hidden = false

  const lbl = document.createElement('span')
  lbl.textContent = 'Driver:'
  lbl.style.cssText = 'color:#8b949e;font-size:11px'
  _driverBox.appendChild(lbl)

  const ovById = new Map(_overhangs().map(o => [o.id, o]))
  // Which duplex side is A vs B in the dropdowns.
  const sideOfA = dx.left.overhang_id === _selA ? 'left' : 'right'
  const sideOfB = sideOfA === 'left' ? 'right' : 'left'
  for (const [side, ovId] of [[sideOfA, _selA], [sideOfB, _selB]]) {
    const btn = document.createElement('button')
    btn.type = 'button'
    const active = dx.driver === side
    btn.textContent = _displayName(ovById.get(ovId)) || ovId
    btn.title = active ? 'Drives (its helix hosts the duplex)' : 'Make this overhang the driver'
    // Individual props (jsdom drops the `background` shorthand in a bulk cssText).
    btn.style.padding = '2px 8px'
    btn.style.borderRadius = '4px'
    btn.style.fontSize = '11px'
    btn.style.cursor = 'pointer'
    btn.style.border = `1px solid ${active ? '#1f6feb' : '#30363d'}`
    btn.style.background = active ? '#1f6feb' : '#161b22'
    btn.style.color = active ? '#fff' : '#c9d1d9'
    btn.addEventListener('click', async (e) => {
      e.stopPropagation()
      if (dx.driver === side) return
      await patchDuplex(dx.id, { driver: side })
    })
    _driverBox.appendChild(btn)
  }
}

function _mkPreviewBox() {
  const d = document.createElement('div')
  d.className = 'oconn-seq-preview'
  d.style.cssText = 'margin:1px 0 5px 2px'
  return d
}

/** Non-complementary warning: for a DIRECT binding, when both overhangs already
 *  have sequences that are NOT reverse-complementary, warn that Pair will
 *  overwrite B with the complement of A. */
/** Number of Watson-Crick complementary positions in the antiparallel overlap of
 *  two overhang sequences (RC(A) aligned with B from the 5' end, over min length).
 *  N positions don't count. Zero = the two share NO complementary region. */
function _complementaryOverlap(aSeq, bSeq) {
  const rcA = _reverseComplement(aSeq).toUpperCase()
  const b = String(bSeq ?? '').toUpperCase()
  const L = Math.min(rcA.length, b.length)
  let n = 0
  for (let i = 0; i < L; i++) if (rcA[i] === b[i] && rcA[i] !== 'N') n++
  return n
}

function _refreshPairWarning() {
  if (!_pairWarnEl) return
  const aSeq = _seqOf(_selA)
  const bSeq = _seqOf(_selB)
  // Only warn when the two sequences share NO complementary region at all. A
  // PARTIAL overlap (e.g. different-length overhangs with a real pairing window)
  // is a valid connection and is no longer flagged.
  const show = ctIsDirect(_typeId) && _selA && _selB && aSeq && bSeq &&
               _complementaryOverlap(aSeq, bSeq) === 0
  _pairWarnEl.hidden = !show
  if (show) {
    _pairWarnEl.textContent =
      '⚠ Overhang A and B sequences share no complementary region.'
  }
}

function _seqOf(id) {
  return (id ? _overhangs().find(o => o.id === id)?.sequence : null) || null
}

// ── Connection versions (candidate specs per pair) ────────────────────────────

function _versions() { return _design()?.connection_versions ?? [] }
function _pairKey(a, b) { return [a, b].sort().join('|') }
function _versionsForPair(a, b) {
  if (!a || !b) return []
  const key = _pairKey(a, b)
  return _versions().filter(v => _pairKey(v.overhang_a_id, v.overhang_b_id) === key)
}
/** Has the current A/B pair ever been connected? (a version OR a live conn/binding) */
function _pairHasConnection() {
  if (!_selA || !_selB) return false
  return _versionsForPair(_selA, _selB).length > 0 || !!_linkerForPair() || !!_bindingForPair()
}

/** Leftmost button: "Connect" a never-paired pair, else "Add version". */
async function _onPrimary() {
  if (!_selA || !_selB) return
  if (_pairHasConnection()) await _onAddVersion()
  else await _onConnect()
}

/** Connect a never-paired pair through the atomic version-Apply endpoint.
 *  Apply tears down every conflicting materialization, installs the requested
 *  direct binding/linker, assigns dependent sequences, and returns final geometry
 *  in one response.  Keeping all connection types on that path avoids geometry
 *  rebuilds for intermediate teardown/create mutations. */
async function _onConnect() {
  if (_genBtn) _genBtn.disabled = true
  try {
    if (ctIsDirect(_typeId)) {
      await _ensureComplementarySequences(true)    // defer re-derive; apply does it once
      // root-to-root binds two sub-domains; without them apply can't create the
      // binding (end-to-root splices instead, so it needs none). Warn like the old
      // Pair path rather than silently materializing an empty connection.
      if (_typeId !== 'end-to-root') {
        const [attachA, attachB] = ctAttachPair(_typeId)
        if (!_subDomainAtAttach(_selA, attachA) || !_subDomainAtAttach(_selB, attachB)) {
          showToast('Sequences set. Binding needs sub-domains defined on both overhangs.')
          return
        }
      }
    }
    await _captureVersion({ applied: true, applyNow: true })
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _render()
  }
}

/** Unapply + tear down every materialized connection/binding (and its version)
 *  that shares overhang `a` or `b`, so the next connect doesn't leave an
 *  overhang in two applied connections. */
async function _teardownConflicts(a, b) {
  const involves = (x) =>
    x.overhang_a_id === a || x.overhang_b_id === a ||
    x.overhang_a_id === b || x.overhang_b_id === b
  for (const v of [..._versions()]) {
    if (v.applied && involves(v)) await patchConnectionVersion(v.id, { applied: false })
  }
  for (const c of [..._connections()]) if (involves(c)) await deleteOverhangConnection(c.id)
  for (const bd of [..._bindings()]) if (involves(bd)) await deleteOverhangBinding(bd.id)
}

/** Add version: snapshot the current form (type/length/live sequences) as a new
 *  version and AUTO-APPLY it (the most recently created version becomes the
 *  materialized one, clearing the pair's prior applied version). */
async function _onAddVersion() {
  if (!_selA || !_selB) return
  if (_genBtn) _genBtn.disabled = true
  try {
    await _captureVersion({ applied: false })       // creates + selects the new version
    if (_selRow?.kind === 'version') await applyConnectionVersion(_selRow.id)
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _render()
  }
}

/** Create a ConnectionVersion from the current form + live overhang sequences. */
async function _captureVersion({ applied, applyNow = false }) {
  const direct = ctIsDirect(_typeId)
  const indirect = ctIsIndirect(_typeId)
  let bridgeLength = 0
  if (!direct && !indirect) bridgeLength = parseInt(_lengthInput?.value ?? '', 10) || 0
  const conn = _linkerForPair()
  const before = new Set(_versions().map(v => v.id))
  const payload = {
    overhang_a_id:  _selA,
    overhang_b_id:  _selB,
    connection_type: _typeId,
    overhang_a_seq: _seqOf(_selA),
    overhang_b_seq: _seqOf(_selB),
    bridge_length:  bridgeLength,
    bridge_seq:     applied ? (conn?.bridge_sequence ?? null) : null,
    applied,
  }
  if (applyNow) await createAndApplyConnectionVersion(payload)
  else await createConnectionVersion(payload)
  const newV = _versions().find(v => !before.has(v.id))
  if (newV) _selRow = { kind: 'version', id: newV.id }
}

/** Apply / Unapply the target version. Apply → atomic backend materialize (sets
 *  sequences + resizes overhangs + recreates the connection type + marks applied).
 *  Unapply → tear down the pair's materialization + clear the version's applied
 *  flag, leaving the overhangs in a free (unconnected) state. */
async function _onApply() {
  const v = _applyTargetVersion()
  if (!v) return
  if (_applyBtn) _applyBtn.disabled = true
  try {
    if (v.applied) {
      await _teardownPair(v.overhang_a_id, v.overhang_b_id)
      await patchConnectionVersion(v.id, { applied: false })
    } else {
      const beforeIds = new Set((_store.getState().currentDesign?.cluster_transforms ?? [])
        .map(c => c.id))
      await applyConnectionVersion(v.id)
      // Apply auto-creates a child DUPLEX cluster (sidebar-listed, gizmo-movable) — tell
      // the user. [[overhang-duplex-cluster]].
      const made = (_store.getState().currentDesign?.cluster_transforms ?? [])
        .find(c => c.overhang_duplex_driver_id && !beforeIds.has(c.id))
      if (made) showToast(`Cluster ${made.name} made from overhangs`)
    }
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _render()
  }
}

/** Tear down the pair's current materialized connection + binding (used when a
 *  user deletes the applied version). */
async function _teardownPair(a, b) {
  const key = _pairKey(a, b)
  const c = _connections().find(x => _pairKey(x.overhang_a_id, x.overhang_b_id) === key)
  if (c) await deleteOverhangConnection(c.id)
  const bd = _bindings().find(x => _pairKey(x.overhang_a_id, x.overhang_b_id) === key)
  if (bd) await deleteOverhangBinding(bd.id)
}

function _gcPercent(seq) {
  if (!seq) return null
  const gc = (seq.match(/[GC]/gi) ?? []).length
  return Math.round((gc / seq.length) * 100)
}

async function _onGenerate() {
  if (!_selA || !_selB) return
  if (ctIsDirect(_typeId)) { await _pair(); return }
  const indirect = ctIsIndirect(_typeId)
  let lengthValue = 0
  if (!indirect) {
    lengthValue = parseFloat(_lengthInput?.value ?? '')
    if (!Number.isFinite(lengthValue) || lengthValue <= 0) {
      showToast('Linker length must be a positive number.')
      return
    }
  }
  const [attachA, attachB] = ctAttachPair(_typeId)
  const payload = {
    overhang_a_id:     _selA,
    overhang_a_attach: attachA,
    overhang_b_id:     _selB,
    overhang_b_attach: attachB,
    linker_type:       ctLinkerType(_typeId),
    length_value:      lengthValue,
    length_unit:       'bp',
  }
  if (_genBtn) _genBtn.disabled = true
  const before = new Set(_connections().map(c => c.id))
  try {
    await createOverhangConnection(payload)   // syncs design → subscriber → _refresh
    const newConn = _connections().find(c => !before.has(c.id))
    if (newConn) _selRow = { kind: 'conn', id: newConn.id }
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _render()
  }
}

/** "Pair" (direct variants): ensure the two overhangs have complementary
 *  sequences, then bind them. Sequence rules:
 *   - neither has a sequence → generate a random one for A, then B = RC(A);
 *   - exactly one missing     → fill the missing one with RC(the present one);
 *   - both present, not complementary → A drives: overwrite B with RC(A);
 *   - both present + already complementary → no sequence change.
 *  Then create the OverhangBinding at each side's attach-end tip sub-domain. */
async function _pair() {
  if (!_selA || !_selB) return
  if (_genBtn) _genBtn.disabled = true
  try {
    await _ensureComplementarySequences()
    await _createBindingForPair()
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _render()
  }
}

/** Make the two overhangs' sequences reverse-complementary (A drives B):
 *   - neither has a sequence → generate a random one for A, then B = RC(A);
 *   - exactly one missing     → fill the missing one with RC(the present one);
 *   - both present, not complementary → A drives: overwrite B with RC(A);
 *   - both present + already complementary → no change.
 *  Leaves A with a sequence in every branch (the end-to-root binder reads RC(A)). */
async function _ensureComplementarySequences(deferReassign = false) {
  // deferReassign: skip the per-write staple re-derivation on the sequence sets below —
  // the CONNECT flow applies the connection right after, which re-derives once with the
  // final topology, so the intermediate re-derivations are redundant. Standalone callers
  // (the Pair path) leave it false so the complements are simulation-ready immediately.
  const aSeq = _seqOf(_selA)
  const bSeq = _seqOf(_selB)
  // Cap the RC to the TARGET overhang's current length so the sequence write
  // never resizes it — different-length overhangs keep their lengths (the longer
  // one keeps its toehold) instead of the shorter being grown to match.
  const rcCapped = (srcSeq, targetId) =>
    capSequenceToLength(_reverseComplement(srcSeq).toUpperCase(),
                        overhangDomainLength(_design(), targetId) ?? undefined)
  const dr = deferReassign ? { deferReassign: true } : {}
  if (!aSeq && !bSeq) {
    await generateOverhangRandomSequence(_selA, dr)                   // new random for A
    const newA = _seqOf(_selA)
    if (newA) await patchOverhang(_selB, { sequence: rcCapped(newA, _selB), ...dr })
  } else if (aSeq && !bSeq) {
    await patchOverhang(_selB, { sequence: rcCapped(aSeq, _selB), ...dr })
  } else if (!aSeq && bSeq) {
    await patchOverhang(_selA, { sequence: rcCapped(bSeq, _selA), ...dr })
  } else if (_reverseComplement(aSeq).toUpperCase() !== bSeq.toUpperCase()) {
    await patchOverhang(_selB, { sequence: rcCapped(aSeq, _selB), ...dr })   // A drives B
  }
}

/** Create the OverhangBinding at each side's attach-end tip sub-domain (after
 *  _pair has made the sequences complementary). */
async function _createBindingForPair() {
  const [attachA, attachB] = ctAttachPair(_typeId)
  const sdAId = _subDomainAtAttach(_selA, attachA)
  const sdBId = _subDomainAtAttach(_selB, attachB)
  if (!sdAId || !sdBId) {
    showToast('Sequences set. Binding needs sub-domains defined on both overhangs.')
    return
  }
  const sdA = (_overhangs().find(o => o.id === _selA)?.sub_domains ?? []).find(sd => sd.id === sdAId)
  const sdB = (_overhangs().find(o => o.id === _selB)?.sub_domains ?? []).find(sd => sd.id === sdBId)
  if (sdA && sdB && sdA.length_bp !== sdB.length_bp) {
    showToast(`Sequences set. Binding not created — tip sub-domains differ (${sdA.length_bp} vs ${sdB.length_bp} bp).`)
    return
  }
  const dup = _bindings().find(b =>
    (b.overhang_a_id === _selA && b.overhang_b_id === _selB) ||
    (b.overhang_a_id === _selB && b.overhang_b_id === _selA))
  if (dup) {
    showToast(`Pair already bound (${dup.name ?? dup.id.slice(0, 6)}).`)
    return
  }
  const before = new Set(_bindings().map(b => b.id))
  await createOverhangBinding({ sub_domain_a_id: sdAId, sub_domain_b_id: sdBId })
  const newB = _bindings().find(b => !before.has(b.id))
  if (newB) _selRow = { kind: 'binding', id: newB.id }
}

// ── Per-side sequence rows (edit + Gen) ───────────────────────────────────────

function _wireSeqRow(side, input, gen) {
  if (!input || !gen) return
  let _last = ''
  input.addEventListener('focus', () => { _last = input.value.trim().toUpperCase() })
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter')  { ev.preventDefault(); input.blur() }
    if (ev.key === 'Escape') { input.value = _last; input.blur() }
  })
  input.addEventListener('blur', async () => {
    const id = side === 'A' ? _selA : _selB
    if (!id) return
    const next = input.value.trim().toUpperCase().replace(/[^ACGTN]/g, '')
    if (next === _last) return
    try { await patchOverhang(id, { sequence: next || null }) }
    catch (err) { showToast(err?.message ?? String(err)); _refreshSeqRows() }
  })
  gen.addEventListener('click', (ev) => { ev.stopPropagation(); _genSide(side) })
}

/** Per-side "Gen": for a DIRECT type, if the OTHER overhang already has a
 *  sequence, fill THIS one with its reverse complement (so they pair); otherwise
 *  (linker types, or the other side empty) generate a random Johnson sequence. */
async function _genSide(side) {
  const thisId  = side === 'A' ? _selA : _selB
  // The connected partner only pairs for DIRECT types; linkers pair via a bridge.
  const otherId = ctIsDirect(_typeId) ? (side === 'A' ? _selB : _selA) : null
  if (!thisId) return
  const gen = side === 'A' ? _seqGenA : _seqGenB
  if (gen) gen.disabled = true
  try {
    await runOverhangGen(thisId, otherId, {
      api: { generateOverhangRandomSequence, patchOverhang },
      getSeq: (id) => _seqOf(id),
      rcOfPartner: (targetId, sourceId) => overhangRcOfPartner(_design(), targetId, sourceId),
    })
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    if (gen) gen.disabled = false
  }
}

// ── Interactive list ──────────────────────────────────────────────────────────

function _renderList() {
  if (!_list) return
  _list.innerHTML = ''
  const nameById = new Map(_overhangs().map(o => [o.id, _displayName(o)]))

  // Group versions by pair → header + indented version rows.
  const groups = new Map()
  for (const v of _versions()) {
    const key = _pairKey(v.overhang_a_id, v.overhang_b_id)
    if (!groups.has(key)) groups.set(key, { a: v.overhang_a_id, b: v.overhang_b_id, versions: [] })
    groups.get(key).versions.push(v)
  }
  // Legacy conns/bindings whose pair has no version group → flat rows.
  const legacy = [
    ..._connections().filter(c => !groups.has(_pairKey(c.overhang_a_id, c.overhang_b_id))).map(c => ['conn', c]),
    ..._bindings().filter(b => !groups.has(_pairKey(b.overhang_a_id, b.overhang_b_id))).map(b => ['binding', b]),
  ]

  if (!groups.size && !legacy.length) {
    const empty = document.createElement('div')
    empty.style.cssText = 'padding:8px;color:#6e7681;text-align:center;font-size:11px'
    empty.textContent = 'No connections yet — pick two overhangs and Connect.'
    _list.appendChild(empty)
    return
  }

  for (const grp of groups.values()) {
    const key = _pairKey(grp.a, grp.b)
    const collapsed = _collapsedGroups.has(key)
    const header = document.createElement('div')
    header.className = 'oconn-group-header'
    const a = nameById.get(grp.a) ?? grp.a
    const b = nameById.get(grp.b) ?? grp.b
    const n = grp.versions.length
    // Connection-type-agnostic title: just the pair + the version count.
    header.innerHTML =
      `<span class="oconn-chevron">${collapsed ? '▸' : '▾'}</span>` +
      `<span>${_esc(a)} ↔ ${_esc(b)} · ${n} version${n !== 1 ? 's' : ''}</span>`
    header.addEventListener('click', () => {
      if (collapsed) _collapsedGroups.delete(key)
      else _collapsedGroups.add(key)
      _renderList()
    })
    _list.appendChild(header)
    if (!collapsed) {
      for (const v of [...grp.versions].sort((x, y) => (x.created_at ?? 0) - (y.created_at ?? 0))) {
        _list.appendChild(_makeVersionRow(v))
      }
    }
  }
  for (const [kind, e] of legacy) _list.appendChild(_makeRow(kind, e, nameById))
}

function _typeShortLabel(type) {
  return CT_VARIANTS.find(x => x.id === type)?.label ?? type
}

function _makeVersionRow(v) {
  const selected = _selRow?.kind === 'version' && _selRow.id === v.id
  const row = document.createElement('div')
  row.className = 'oconn-version-row' + (selected ? ' is-selected' : '') + (v.applied ? ' is-applied' : '')
  row.dataset.versionId = v.id
  const metrics = []
  if (v.overhang_a_seq) metrics.push(`${v.overhang_a_seq.length}nt`)
  const gc = _gcPercent(v.overhang_a_seq)
  if (gc != null) metrics.push(`GC ${gc}%`)
  if (v.bridge_length) metrics.push(`bridge ${v.bridge_length}bp`)
  const main = document.createElement('div')
  main.className = 'oconn-row-main'
  main.innerHTML =
    `<span class="oconn-row-name">${_esc(v.name || 'V?')}</span>` +
    (v.applied ? ' <span class="oconn-applied-badge">●&nbsp;applied</span>' : '') +
    ` <span class="oconn-row-summary">${_esc(_typeShortLabel(v.connection_type))}` +
    `${metrics.length ? ' · ' + _esc(metrics.join(' · ')) : ''}</span>`
  row.appendChild(main)
  const del = document.createElement('button')
  del.className = 'oconn-row-del'
  del.type = 'button'
  del.textContent = '×'
  del.title = 'Delete version'
  del.addEventListener('click', (ev) => { ev.stopPropagation(); _deleteVersion(v) })
  row.appendChild(del)
  row.addEventListener('click', () => _selectVersion(v))
  return row
}

function _selectVersion(v) {
  _selRow = { kind: 'version', id: v.id }
  _selA = v.overhang_a_id ?? null
  _selB = v.overhang_b_id ?? null
  _slotTA = _selA ? ++_clock : 0
  _slotTB = _selB ? ++_clock : 0
  if (CT_VARIANTS.some(x => x.id === v.connection_type)) {
    _typeId = v.connection_type
    try { localStorage.setItem(_STORAGE, v.connection_type) } catch { /* ignore */ }
  }
  if (_lengthInput && v.bridge_length) _lengthInput.value = String(v.bridge_length)
  if (_selectA) _selectA.value = _selA ?? ''
  if (_selectB) _selectB.value = _selB ?? ''
  _render()
}

async function _deleteVersion(v) {
  const ok = await showConfirm({
    title: 'Delete version',
    message: `Delete version "${v.name || 'V?'}"${v.applied ? ' (also removes its materialized connection)' : ''}?`,
    danger: true,
    confirmLabel: 'Delete',
  })
  if (!ok) return
  try {
    if (_selRow?.kind === 'version' && _selRow.id === v.id) _selRow = null
    if (v.applied) await _teardownPair(v.overhang_a_id, v.overhang_b_id)
    await deleteConnectionVersion(v.id)
  } catch (err) {
    showToast(err?.message ?? String(err))
  }
}

function _makeRow(kind, e, nameById) {
  const isConn = kind === 'conn'
  const selected = _selRow && _selRow.kind === kind && _selRow.id === e.id
  const row = document.createElement('div')
  row.className = 'oconn-row' + (selected ? ' is-selected' : '')
  if (isConn) row.dataset.connId = e.id
  else        row.dataset.bindingId = e.id
  const a = nameById.get(e.overhang_a_id) ?? e.overhang_a_id ?? '?'
  const b = nameById.get(e.overhang_b_id) ?? e.overhang_b_id ?? '?'
  const type = isConn ? (e.linker_type === 'ds' ? 'dsDNA' : 'ssDNA') : 'Binding'
  const len = (isConn && Number(e.length_value) > 0)
    ? ` ${e.length_value}${e.length_unit === 'nm' ? 'nm' : 'bp'}` : ''
  const main = document.createElement('div')
  main.className = 'oconn-row-main'
  main.innerHTML =
    `<span class="oconn-row-name">${_esc(e.name ?? e.id.slice(0, 6))}</span> ` +
    `<span class="oconn-row-summary">${_esc(type)}${_esc(len)} · ${_esc(a)} ↔ ${_esc(b)}</span>`
  row.appendChild(main)
  const del = document.createElement('button')
  del.className = 'oconn-row-del'
  del.type = 'button'
  del.textContent = '×'
  del.title = isConn ? 'Delete linker' : 'Delete binding'
  del.addEventListener('click', (ev) => { ev.stopPropagation(); _deleteEntity(kind, e) })
  row.appendChild(del)
  row.addEventListener('click', () => _selectRow(kind, e))
  return row
}

/** Click a list row → select it (show its sequence/details), re-populate the
 *  two overhang dropdowns + (for linkers) the matching connection-type variant. */
function _selectRow(kind, e) {
  _selRow = { kind, id: e.id }
  _selA = e.overhang_a_id ?? null
  _selB = e.overhang_b_id ?? null
  _slotTA = _selA ? ++_clock : 0
  _slotTB = _selB ? ++_clock : 0
  if (kind === 'conn') {
    const variant = ctVariantForConnection(e)
    if (variant && CT_VARIANTS.some(v => v.id === variant)) {
      _typeId = variant
      try { localStorage.setItem(_STORAGE, variant) } catch { /* ignore */ }
    }
  }
  if (_selectA) _selectA.value = _selA ?? ''
  if (_selectB) _selectB.value = _selB ?? ''
  _render()
}

async function _deleteEntity(kind, e) {
  const label = kind === 'binding' ? 'binding' : 'linker'
  const ok = await showConfirm({
    title: `Delete ${label}`,
    message: `Delete ${label} "${e.name ?? e.id.slice(0, 6)}"?`,
    danger: true,
    confirmLabel: 'Delete',
  })
  if (!ok) return
  try {
    if (_selRow && _selRow.kind === kind && _selRow.id === e.id) _selRow = null
    if (kind === 'conn') await deleteOverhangConnection(e.id)
    else                 await deleteOverhangBinding(e.id)
  } catch (err) {
    showToast(err?.message ?? String(err))
  }
}

// ── Selected-row details (sequence + edit) ────────────────────────────────────

/** Render the details panel for the selected list row: the computed sequence
 *  plus the one editable backend field (bridge sequence for linkers, Bound
 *  toggle for bindings). Re-fetches live design state each call; skips the
 *  rebuild while the bridge input is focused (so it doesn't clobber typing). */
function _renderDetails() {
  if (!_detailsEl) return
  if (document.activeElement?.id === 'oconn-bridge-input' ||
      document.activeElement?.dataset?.vseq) return                // mid-edit guard
  if (!_selRow) { _detailsEl.hidden = true; _detailsEl.innerHTML = ''; return }
  if (_selRow.kind === 'version') {
    const v = _versions().find(x => x.id === _selRow.id)
    if (!v) { _detailsEl.hidden = true; _detailsEl.innerHTML = ''; return }
    _renderVersionDetails(v)
  } else if (_selRow.kind === 'conn') {
    const conn = _connections().find(c => c.id === _selRow.id)
    if (!conn) { _detailsEl.hidden = true; _detailsEl.innerHTML = ''; return }
    _renderLinkerDetails(conn)
  } else {
    const binding = _bindings().find(b => b.id === _selRow.id)
    if (!binding) { _detailsEl.hidden = true; _detailsEl.innerHTML = ''; return }
    _renderBindingDetails(binding)
  }
  _detailsEl.hidden = false
}

function _renderVersionDetails(v) {
  _detailsEl.innerHTML = ''
  const nameById = new Map(_overhangs().map(o => [o.id, _displayName(o)]))
  const title = document.createElement('div')
  title.style.cssText = 'color:#8b949e;margin-bottom:4px'
  title.textContent = `${v.name || 'Version'} — ${_typeShortLabel(v.connection_type)}${v.applied ? ' (applied)' : ''}`
  _detailsEl.appendChild(title)

  // For direct types, a colored preview of how the LIVE overhangs currently pair
  // (green = complementary, amber = mismatch/N, grey = excess / undefined tail),
  // anchored at the connection-type attach sub-domain. The editable snapshot
  // fields below remain the version's own stored sequences.
  if (ctIsDirect(v.connection_type)) {
    const lines = _pairingLineEls({ aId: v.overhang_a_id, bId: v.overhang_b_id, type: v.connection_type })
    if (lines.length) {
      const cap = document.createElement('div')
      cap.style.cssText = 'color:#6e7681;font-size:10px;margin-bottom:2px'
      cap.textContent = 'Current overhang pairing:'
      _detailsEl.appendChild(cap)
      for (const line of lines) _detailsEl.appendChild(line)
    }
  }

  const _seqInput = (value, placeholder, onCommit) => {
    const input = document.createElement('input')
    input.type = 'text'; input.spellcheck = false
    input.value = value ?? ''
    input.placeholder = placeholder ?? ''
    input.dataset.vseq = '1'
    input.style.cssText = 'flex:1;min-width:0;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-family:monospace;font-size:11px;padding:3px 5px;outline:none'
    let last = (input.value || '').toUpperCase()
    input.addEventListener('focus', () => { last = input.value.trim().toUpperCase() })
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter')  { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { input.value = last; input.blur() }
    })
    input.addEventListener('blur', async () => {
      const next = input.value.trim().toUpperCase().replace(/[^ACGTN]/g, '')
      if (next === last) return
      try { await onCommit(next) }
      catch (err) { showToast(err?.message ?? String(err)) }
    })
    return input
  }

  for (const [side, ovId, seqKey, color] of [
    ['A', v.overhang_a_id, 'overhang_a_seq', _NEON_A],
    ['B', v.overhang_b_id, 'overhang_b_seq', _NEON_B],
  ]) {
    const row = document.createElement('div')
    row.style.cssText = 'display:flex;gap:4px;align-items:center;margin-bottom:4px'
    const lab = document.createElement('span')
    lab.style.cssText = `color:${color};font-size:11px;width:64px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`
    lab.textContent = nameById.get(ovId) ?? side
    row.append(lab, _seqInput(v[seqKey], 'sequence…', (next) => patchConnectionVersion(v.id, { [seqKey]: next })))
    _detailsEl.appendChild(row)
  }

  if (!ctIsDirect(v.connection_type) && !ctIsIndirect(v.connection_type)) {
    const row = document.createElement('div')
    row.style.cssText = 'display:flex;gap:4px;align-items:center;margin-bottom:4px'
    const lab = document.createElement('span')
    lab.style.cssText = 'color:#8b949e;font-size:11px;width:64px'
    lab.textContent = 'Bridge'
    row.append(lab, _seqInput(v.bridge_seq, v.bridge_length ? `${v.bridge_length} nt` : '', (next) => patchConnectionVersion(v.id, { bridge_seq: next })))
    _detailsEl.appendChild(row)
  }

  const hint = document.createElement('div')
  hint.style.cssText = 'color:#6e7681;font-size:10px;margin-top:2px'
  hint.textContent = v.applied
    ? 'Applied. Edit then click Apply to update the model.'
    : 'Draft — click Apply to materialize this version.'
  _detailsEl.appendChild(hint)
}

function _renderLinkerDetails(conn) {
  _detailsEl.innerHTML = ''
  const title = document.createElement('div')
  title.style.cssText = 'color:#8b949e;margin-bottom:4px'
  title.textContent = `${conn.name ?? 'Linker'} — sequence (5'→3')`
  _detailsEl.appendChild(title)

  // Colored strand lines (complement portions + bridge), live-computed.
  for (const segs of _linkerStrandSegments(conn)) {
    const line = document.createElement('div')
    line.style.cssText = 'white-space:nowrap;letter-spacing:0.04em;font-family:monospace;font-size:11px'
    for (const s of segs.segments) {
      const span = document.createElement('span')
      span.textContent = s.text
      span.style.color = s.color
      line.appendChild(span)
    }
    _detailsEl.appendChild(line)
  }

  // Bridge-sequence editor (the user-settable portion of the linker sequence).
  const lenBp = _linkerLengthInBp(conn)
  const row = document.createElement('div')
  row.style.cssText = 'display:flex;gap:4px;align-items:center;margin-top:6px'
  const label = document.createElement('span')
  label.style.cssText = 'color:#8b949e'
  label.textContent = 'Bridge'
  const input = document.createElement('input')
  input.id = 'oconn-bridge-input'
  input.type = 'text'
  input.spellcheck = false
  input.value = conn.bridge_sequence ?? ''
  input.placeholder = Number.isFinite(lenBp) ? `${lenBp} nt` : ''
  input.style.cssText = 'flex:1;min-width:0;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-family:monospace;font-size:11px;padding:3px 5px;outline:none'
  let _last = input.value.toUpperCase()
  input.addEventListener('focus', () => { _last = input.value.trim().toUpperCase() })
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter')  { ev.preventDefault(); input.blur() }
    if (ev.key === 'Escape') { input.value = _last; input.blur() }
  })
  input.addEventListener('blur', async () => {
    const next = input.value.trim().toUpperCase().replace(/[^ACGTN]/g, '')
    if (next === _last) return
    try { await patchOverhangConnection(conn.id, { bridge_sequence: next }) }
    catch (err) { showToast(err?.message ?? String(err)) }
  })
  const gen = document.createElement('button')
  gen.type = 'button'
  gen.textContent = 'Gen'
  gen.title = 'Generate a random bridge sequence of the linker length'
  gen.style.cssText = 'padding:3px 8px;background:#21262d;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-family:monospace;font-size:11px;cursor:pointer'
  gen.disabled = !Number.isFinite(lenBp) || lenBp <= 0
  gen.addEventListener('click', async () => {
    if (!Number.isFinite(lenBp) || lenBp <= 0) return
    gen.disabled = true
    try {
      showToast('Using the Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
      const seq = await generateRandomSequence(lenBp)
      if (seq) await patchOverhangConnection(conn.id, { bridge_sequence: seq })
    } catch (err) { showToast(err?.message ?? String(err)) }
    finally { gen.disabled = false }
  })
  row.append(label, input, gen)
  _detailsEl.appendChild(row)
}

function _renderBindingDetails(binding) {
  _detailsEl.innerHTML = ''
  const title = document.createElement('div')
  title.style.cssText = 'color:#8b949e;margin-bottom:4px'
  title.textContent = `${binding.name ?? 'Binding'} — paired sub-domains`
  _detailsEl.appendChild(title)

  const sdLookup = new Map()
  for (const o of _overhangs()) {
    for (const sd of (o.sub_domains ?? [])) sdLookup.set(sd.id, { ovhg: o, sd })
  }
  const a = sdLookup.get(binding.sub_domain_a_id)
  const b = sdLookup.get(binding.sub_domain_b_id)
  // Pairing preview anchored at the bound sub-domains (no guessing — the binding
  // stores exactly which sub-domains hybridize). Green = complementary, amber =
  // mismatch/N inside the bound region, grey = excess / undefined N tail.
  const aId = binding.overhang_a_id ?? a?.ovhg?.id
  const bId = binding.overhang_b_id ?? b?.ovhg?.id
  const lines = _pairingLineEls({
    aId, bId, type: 'root-to-root',
    sdAId: binding.sub_domain_a_id, sdBId: binding.sub_domain_b_id,
  })
  if (lines.length) {
    for (const line of lines) _detailsEl.appendChild(line)
  } else {
    for (const [side, ent, color] of [['A', a, _NEON_A], ['B', b, _NEON_B]]) {
      const line = document.createElement('div')
      line.style.cssText = `white-space:nowrap;letter-spacing:0.04em;font-family:monospace;font-size:11px;color:${color}`
      line.textContent = `${side}: ${_resolveSubDomainSeq(ent?.ovhg, ent?.sd) || '(empty)'}`
      _detailsEl.appendChild(line)
    }
  }

  // Bound toggle (the binding's one backend-mutable bit).
  const row = document.createElement('label')
  row.style.cssText = 'display:flex;gap:6px;align-items:center;margin-top:6px;color:#c9d1d9;cursor:pointer'
  const cb = document.createElement('input')
  cb.type = 'checkbox'
  cb.checked = !!binding.bound
  cb.addEventListener('change', async () => {
    const next = cb.checked
    cb.disabled = true
    try {
      const res = await patchOverhangBinding(binding.id, { bound: next })
      if (res == null) { cb.checked = !next; showToast('Could not change bound state.') }
    } catch (err) { cb.checked = !next; showToast(err?.message ?? String(err)) }
    finally { cb.disabled = false }
  })
  const lbl = document.createElement('span')
  lbl.textContent = 'Bound (hybridized)'
  row.append(cb, lbl)
  _detailsEl.appendChild(row)
}

// Resolve a sub-domain's sequence from its overhang (override wins, else the
// overhang's sequence sliced to the sub-domain span). Mirrors the manager.
function _resolveSubDomainSeq(ovhg, sd) {
  if (!ovhg || !sd) return null
  if (sd.sequence_override) return sd.sequence_override.toUpperCase()
  if (!ovhg.sequence) return null
  const start = sd.start_bp_offset ?? 0
  const end = start + (sd.length_bp ?? 0)
  return ovhg.sequence.slice(start, end).toUpperCase()
}

// Linker bridge length in bp (nm → bp via B-DNA rise). Mirrors the manager.
function _linkerLengthInBp(conn) {
  if (!conn) return NaN
  const v = Number(conn.length_value)
  if (!Number.isFinite(v) || v <= 0) return NaN
  return conn.length_unit === 'nm' ? Math.max(1, Math.round(v / 0.334)) : Math.round(v)
}

// Colored span list for every linker strand of one connection — live-computed
// from current overhang sequences (RC) + conn.bridge_sequence, NOT from stored
// strand.sequence. Verbatim port of the manager's `_linkerStrandSegments`.
function _linkerStrandSegments(conn) {
  const design = _design()
  if (!design) return []
  const prefix = `__lnk__${conn.id}`
  const strands = (design.strands ?? [])
    .filter(s => s.id.startsWith(prefix))
    .sort((a, b) => a.id.localeCompare(b.id))
  const ovhgById = new Map((design.overhangs ?? []).map(o => [o.id, o]))
  const aSeq = ovhgById.get(conn.overhang_a_id)?.sequence ?? null
  const bSeq = ovhgById.get(conn.overhang_b_id)?.sequence ?? null
  const userBridge = (conn.bridge_sequence ?? '').toUpperCase()
  const pad = (seq, length) =>
    seq.length >= length ? seq.slice(0, length) : seq + 'N'.repeat(length - seq.length)

  const out = []
  for (const strand of strands) {
    const suffix = strand.id.slice(prefix.length + 2)  // 'a' | 'b' | 's'
    const bridgeColor = conn.linker_type === 'ds'
      ? (suffix === 'a' ? _LINKER_DS_A_COLOR : _LINKER_DS_B_COLOR)
      : _LINKER_BRIDGE_COLOR
    const thisBridge = conn.linker_type === 'ds' && suffix === 'b'
      ? _reverseComplement(userBridge)
      : userBridge
    const segments = []
    let complementsSeen = 0
    for (const dom of strand.domains ?? []) {
      const length = Math.max(0, Math.abs((dom.end_bp ?? 0) - (dom.start_bp ?? 0)) + 1)
      if (length === 0) continue
      const isBridge = (dom.helix_id ?? '').startsWith('__lnk__')
      if (isBridge) {
        const text = thisBridge ? pad(thisBridge, length) : 'N'.repeat(length)
        segments.push({ text, color: bridgeColor })
      } else {
        const ohSide = suffix === 'a' ? 'A'
                     : suffix === 'b' ? 'B'
                     : (complementsSeen === 0 ? 'A' : 'B')
        const targetSeq = ohSide === 'A' ? aSeq : bSeq
        const ohSeq = (targetSeq ?? '').slice(0, length).padEnd(length, 'N')
        segments.push({ text: _reverseComplement(ohSeq), color: ohSide === 'A' ? _NEON_A : _NEON_B })
        complementsSeen += 1
      }
    }
    out.push({ strandId: strand.id, segments })
  }
  return out
}

// ── Small pure helpers (mirror the manager) ───────────────────────────────────

function _subDomainAtAttach(ovhgId, attach /* 'root' | 'free_end' */) {
  const ov = _overhangs().find(o => o.id === ovhgId)
  if (!ov || !ov.sub_domains?.length) return null
  const sorted = [...ov.sub_domains].sort((x, y) => (x.start_bp_offset ?? 0) - (y.start_bp_offset ?? 0))
  return attach === 'root' ? sorted[0].id : sorted[sorted.length - 1].id
}

// ── Sequence-preview rendering (N-padding + complementary coloring) ────────────

/** Full assembled bases of an overhang, 5'→3', N-padded to its CURRENT backing-
 *  domain length — so bases left undefined after the user drags the overhang
 *  longer show as 'N'. */
function _overhangBases(ovhg) {
  if (!ovhg) return ''
  return assembleOverhangSequence(ovhg, overhangDomainLength(_design(), ovhg.id) ?? undefined)
}

/** The bound (duplex) region within one overhang's assembled bases: an explicit
 *  sub-domain id (a binding's stored pair) wins; else the connection-type attach
 *  sub-domain (root = first, free_end = last). `{start, len}` indexes into
 *  `_overhangBases(ovhg)`. */
function _boundRegion(ovhg, attach, sdId) {
  const subs = [...(ovhg?.sub_domains ?? [])].sort((x, y) => (x.start_bp_offset ?? 0) - (y.start_bp_offset ?? 0))
  let sd = sdId ? subs.find(s => s.id === sdId) : null
  if (!sd) sd = attach === 'root' ? subs[0] : subs[subs.length - 1]
  if (!sd) return { start: 0, len: 0 }
  return { start: sd.start_bp_offset ?? 0, len: sd.length_bp ?? 0 }
}

/** Build a monospace line of colored <span>s from `{text, color}` segments,
 *  prefixed with an optional dimmed label. */
function _seqLineEl(label, segments) {
  const line = document.createElement('div')
  line.style.cssText = 'white-space:nowrap;letter-spacing:0.06em;font-family:monospace;font-size:11px;line-height:1.5'
  if (label != null) {
    const l = document.createElement('span')
    l.style.cssText = 'color:#8b949e;margin-right:5px'
    l.textContent = `${label}:`
    line.appendChild(l)
  }
  for (const s of segments) {
    if (!s.text) continue
    const span = document.createElement('span')
    span.textContent = s.text
    span.style.color = s.color
    line.appendChild(span)
  }
  return line
}

/** Two colored preview lines (A then B) showing which bases hybridize vs are
 *  excess/unpaired for a DIRECT overhang pair, anchored at the bound/attach
 *  sub-domain. `sdAId/sdBId` (a binding's stored pair) override the type's
 *  attach sub-domain. Returns [] when either overhang is missing. */
function _pairingLineEls({ aId, bId, type, sdAId = null, sdBId = null }) {
  const aOv = _overhangs().find(o => o.id === aId)
  const bOv = _overhangs().find(o => o.id === bId)
  if (!aOv || !bOv) return []
  const aBases = _overhangBases(aOv)
  const bBases = _overhangBases(bOv)
  const [attachA, attachB] = ctAttachPair(type)
  const ra = _boundRegion(aOv, attachA, sdAId)
  const rb = _boundRegion(bOv, attachB, sdBId)
  const pairLen = Math.min(ra.len, rb.len)
  const { a, b } = pairingSegments(aBases, bBases, ra.start, rb.start, pairLen)
  const toColored = (segs) => segs.map(s => ({ text: s.text, color: _PAIR_COLOR[s.kind] }))
  return [
    _seqLineEl(_displayName(aOv) || 'A', toColored(a)),
    _seqLineEl(_displayName(bOv) || 'B', toColored(b)),
  ]
}

/** One preview line for a single overhang (no pairing context): defined bases
 *  neutral, undefined N greyed — so a dragged-longer overhang's undefined tail
 *  is visible. */
function _simpleSeqLineEl(label, ovhg) {
  const bases = _overhangBases(ovhg)
  const segs = []
  for (const ch of bases) {
    const color = ch === 'N' ? _SEQ_UNDEFINED_COLOR : _SEQ_DEFINED_COLOR
    const prev = segs[segs.length - 1]
    if (prev && prev.color === color) prev.text += ch
    else segs.push({ text: ch, color })
  }
  return _seqLineEl(label, segs)
}

function _reverseComplement(seq) {
  if (!seq) return ''
  const map = { A: 'T', T: 'A', C: 'G', G: 'C', N: 'N', a: 't', t: 'a', c: 'g', g: 'c', n: 'n' }
  let out = ''
  for (let i = seq.length - 1; i >= 0; i--) out += map[seq[i]] ?? seq[i]
  return out
}

function _esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, ch =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]))
}

function _buildPopover() {
  _popover.innerHTML = ''
  for (const v of CT_VARIANTS) {
    const opt = document.createElement('button')
    opt.type = 'button'
    opt.className = 'ct-option'
    opt.dataset.variant = v.id
    opt.setAttribute('role', 'option')
    opt.title = v.label
    opt.addEventListener('click', (ev) => {
      ev.stopPropagation()
      _typeId = v.id
      try { localStorage.setItem(_STORAGE, v.id) } catch { /* ignore */ }
      _render()
      _closePopover()
    })
    _popover.appendChild(opt)
  }
  _refreshPopoverTiles()
}

function _refreshPopoverTiles() {
  if (!_popover) return
  const L = endOf(_selA)
  const R = endOf(_selB)
  const hasA = _selA != null
  const hasB = _selB != null
  for (const opt of _popover.querySelectorAll('.ct-option')) {
    const id = opt.dataset.variant
    const forbidden = hasA && hasB && ctIsForbidden(id, L, R)
    opt.innerHTML = `<div class="ct-tile">${ctTileSvg(id, L, R, forbidden, hasA, hasB)}</div>`
    opt.classList.toggle('is-selected', id === _typeId)
  }
}

function _applyCollapse() {
  if (!_body) return
  _body.style.display = _collapsed ? 'none' : ''
  if (_arrow) _arrow.classList.toggle('is-collapsed', _collapsed)
  if (_collapsed) {
    _closePopover()
    _updateGlow()   // collapsing clears the cyan/magenta overhang highlight
  } else if (_selA || _selB) {
    // Opening snaps the dropdowns to whatever the slots hold (the current scene
    // selection) and re-shows the highlight (via _render → _updateGlow).
    _applySlotsToDropdowns()
  } else {
    _updateGlow()   // open with nothing selected → ensure no highlight
  }
}

// ── Auto-populate from 3D scene selection ─────────────────────────────────────

/** Ordered, valid list of overhang ids from canonical selection. */
function _selectedOverhangIds(state) {
  const valid = new Set(_overhangs().map(o => o.id))
  return selectedOverhangIds(state).filter(id => valid.has(id))
}

/** Translate a scene-selection change into newly-picked overhang ids and feed
 *  them into the 2-slot LRU, then (when open) drive the dropdowns. The "picks"
 *  derived per event make lasso / ctrl-shift / sequential all behave the same:
 *   - exactly 1 selected → that id is THE pick (a single click, even when it
 *     replaces a larger prior selection),
 *   - ≥2 selected → the ids new vs. the previous selection (array order) — one
 *     for a ctrl/shift add, many for a fresh lasso,
 *   - 0 selected → no pick (a transient deselect leaves the slots alone). */
function _onSelectionChange(state) {
  const cur = _selectedOverhangIds(state)
  let picks
  if (cur.length === 1) picks = cur
  else if (cur.length >= 2) picks = cur.filter(id => !_selPrev.includes(id))
  else picks = []
  for (const id of picks) _placePick(id)
  _selPrev = cur
  if (_collapsed) return   // only drive the dropdowns while the section is open
  _applySlotsToDropdowns()
}

/** Place one freshly-picked overhang into the 2-slot LRU: no-op if already
 *  shown; else fill an empty slot; else evict the slot populated less recently. */
function _placePick(id) {
  if (!id || id === _selA || id === _selB) return   // already shown / invalid
  if (_selA == null)         { _selA = id; _slotTA = ++_clock; return }
  if (_selB == null)         { _selB = id; _slotTB = ++_clock; return }
  if (_slotTA <= _slotTB)    { _selA = id; _slotTA = ++_clock }   // A is older → evict A
  else                       { _selB = id; _slotTB = ++_clock }   // B is older → evict B
}

/** Push the current slots into the A / B dropdowns. */
function _applySlotsToDropdowns() {
  _selRow = null   // a fresh scene selection is not a list-row selection
  if (_selectA) _selectA.value = _selA ?? ''
  if (_selectB) _selectB.value = _selB ?? ''
  _render()
}

function _openPopover() {
  // The right panel clips overflow, so float the popover in viewport coords
  // anchored under the button-box. The section lives in the RIGHT sidebar, so
  // grow the popover LEFTWARD (align its right edge to the button's right edge)
  // — otherwise its 4-wide grid is clipped by the screen's right edge.
  const r = _box.getBoundingClientRect()
  _popover.style.position = 'fixed'
  _popover.style.left = '0px'   // reset before measuring width
  _popover.hidden = false       // must be visible to measure offsetWidth
  const pw = _popover.offsetWidth || 0
  const vw = window.innerWidth || 0
  let left = r.right - pw                 // right edge of popover ↔ right edge of button
  if (vw) left = Math.min(left, vw - pw - 8)
  left = Math.max(8, left)
  _popover.style.left = `${Math.round(left)}px`
  _popover.style.top  = `${Math.round(r.bottom + 6)}px`
  _box.setAttribute('aria-expanded', 'true')
}

function _closePopover() {
  _popover.hidden = true
  _box.setAttribute('aria-expanded', 'false')
}

/** Open the section for a specific overhang PAIR and select the connection's
 *  currently-applied version (falling back to the live linker / binding row, or
 *  nothing if neither exists). Called from the Overhangs list's per-row link
 *  icon — a singleton entry point, so callers import it directly rather than
 *  threading the panel's api through main.js. No-op when the section DOM is
 *  absent (e.g. before init, or in a headless test without the markup). */
export function openConnectionForPair(aId, bId) {
  if (!_inited || !_selectA || !_selectB) return
  _selA = aId || null
  _selB = bId || null
  _slotTA = _selA ? ++_clock : 0
  _slotTB = _selB ? ++_clock : 0
  // Expand if collapsed (this snaps the dropdowns to the slots + clears _selRow).
  if (_collapsed) { _collapsed = false; _applyCollapse() }
  if (_selectA) _selectA.value = _selA ?? ''
  if (_selectB) _selectB.value = _selB ?? ''
  // Select the pair's applied version, else its live linker / binding row.
  const applied = _versionsForPair(_selA, _selB).find(v => v.applied)
  const c = _linkerForPair()
  const b = c ? null : _bindingForPair()
  _selRow = applied ? { kind: 'version', id: applied.id }
          : c       ? { kind: 'conn',    id: c.id }
          : b       ? { kind: 'binding', id: b.id }
          :           null
  _render()
  _heading?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
}

const _api = {
  /** Re-read the design and rebuild (exposed for callers / tests). */
  refresh: _refresh,
  /** Open the section for a pair + select its applied version (link-icon entry). */
  openConnectionForPair,
}
