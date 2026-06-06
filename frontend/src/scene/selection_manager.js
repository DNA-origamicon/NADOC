/**
 * Selection manager — raycaster-based click-to-select with three-click model.
 *
 * Click model (beads and cones both participate):
 *   First click on a bead/cone  → select the entire strand.
 *   Second click on a bead      → select that individual nucleotide.
 *   Click on same bead again    → deselect (clear selection).
 *   Click on a different bead (bead mode, same strand) → select that bead.
 *   Second click on a cone      → select that individual cone.
 *   Click on empty space        → clear selection (unless zoom scope pre-hover active).
 *
 * Modifier semantics (remapped 2026-05-17):
 *   Ctrl+left-drag             → rectangle lasso multi-select.
 *   Ctrl+left-click (no drag)  → no-op (was bead/arc toggle pre-remap).
 *   Alt+left-click             → toggle backbone bead in _ctrlBeads (distance measurement).
 *   Shift+left-click           → toggle hit strand in multiSelectedStrandIds
 *                                (or hit crossover arc in multi-arc set when
 *                                 selectableTypes.crossoverArcs is on).
 *
 * Right-click behaviour:
 *   On a cone (any mode) → "Nick here" context menu.
 *   On a bead (strand or domain selected) → colour-picker menu.
 *   On a bead (bead mode) → loop/skip menu.
 *
 * Selection state is stored in the store as selectedObject:
 *   { type: 'strand',     id, data: { strand_id } }
 *   { type: 'domain',     id, data: { strand_id, domain_index, helix_id, direction, overhang_id } }
 *   { type: 'nucleotide', id, data: nuc }
 *   { type: 'cone',       id, data: { fromNuc, toNuc, strand_id } }
 *   null — nothing selected
 */

import * as THREE from 'three'
import { store, pushGroupUndo } from '../state/store.js'
import * as api from '../api/client.js'
import { ensureLoaded as _ensureFjcLookup } from './ssdna_fjc.js'
import { showConfirm } from '../ui/primitives/confirm.js'
import { clusterMemberFilter } from './cluster_gizmo.js'
import { strandsToSegments, clustersToSegments, domainsToSegments, editOverridesForSegments, createRepresentationMenuItem } from './representation_overrides.js'
import { isDrillV2, normalizeLevel, hoverPreviewTarget, lassoCaptureType } from './selection_level.js'

// Kick off the FJC lookup fetch at module load so the linker-config modal
// opens instantly with the per-bin histograms already cached.
_ensureFjcLookup().catch(() => {})

// ── Colour constants ───────────────────────────────────────────────────────────

const C_SELECT_BEAD          = 0xffffff
const C_SELECT_CONE          = 0xffffff
const C_SELECT_STRAND        = 0xffffff
const C_FIVE_PRIME  = 0xff4444   // glowing red — 5′ end
const C_THREE_PRIME = 0x4488ff   // glowing blue — 3′ end

const PICKER_COLORS = [
  { hex: 0xff6b6b, css: '#ff6b6b', label: 'Coral'      },
  { hex: 0xffd93d, css: '#ffd93d', label: 'Amber'      },
  { hex: 0x6bcb77, css: '#6bcb77', label: 'Green'      },
  { hex: 0xf9844a, css: '#f9844a', label: 'Orange'     },
  { hex: 0xa29bfe, css: '#a29bfe', label: 'Lavender'   },
  { hex: 0xff9ff3, css: '#ff9ff3', label: 'Pink'       },
  { hex: 0x00cec9, css: '#00cec9', label: 'Teal'       },
  { hex: 0xe17055, css: '#e17055', label: 'Terracotta' },
  { hex: 0x74b9ff, css: '#74b9ff', label: 'Steel blue' },
  { hex: 0x55efc4, css: '#55efc4', label: 'Mint'       },
  { hex: 0xfdcb6e, css: '#fdcb6e', label: 'Yellow'     },
  { hex: 0xd63031, css: '#d63031', label: 'Crimson'    },
]

function linkerConnectionIdFromStrandId(strandId) {
  // Matches ds linker halves (`__a` / `__b`) and the ss single-strand bridge (`__s`).
  const m = /^__lnk__(.+)__(a|b|s)$/.exec(strandId ?? '')
  return m ? m[1] : null
}

function linkerConnectionForStrandId(strandId) {
  const connId = linkerConnectionIdFromStrandId(strandId)
  if (!connId) return null
  return store.getState().currentDesign?.overhang_connections?.find(c => c.id === connId) ?? null
}

function linkerLabel(conn) {
  return conn?.name || conn?.id || 'linker'
}

/** Return every component strand id that makes up the linker the given strand
 *  belongs to. Selecting / coloring / right-clicking treats the linker as one
 *  unit, so both ds halves go together. */
function linkerComponentIds(strandId) {
  const connId = linkerConnectionIdFromStrandId(strandId)
  if (!connId) return [strandId].filter(Boolean)
  const design = store.getState().currentDesign
  const conn = design?.overhang_connections?.find(c => c.id === connId)
  if (conn?.linker_type === 'ss') return [`__lnk__${conn.id}__s`]
  return [`__lnk__${conn.id}__a`, `__lnk__${conn.id}__b`]
}

async function deleteEntireLinker(connId) {
  const conn = store.getState().currentDesign?.overhang_connections?.find(c => c.id === connId)
  if (!conn) return
  const ok = await showConfirm({
    title: `Delete linker ${linkerLabel(conn)}`,
    message: `Delete entire linker "${linkerLabel(conn)}"?`,
    danger: true,
    confirmLabel: 'Delete',
  })
  if (!ok) return
  await api.deleteOverhangConnection(conn.id)
}

// Mirrors backend `dof_topology` so the linker context menu can render the
// "Relax Linker" entry enabled or grayed out without an extra API call.
// Both ds and ss linkers relax — ds toward duplex visualLength, ss toward
// the FJC mean R_ee from backend/data/ssdna_fjc_lookup.json.
function _linkerRelaxStatus(design, conn) {
  if (!design || !conn) return { available: false, reason: 'No linker.', n_dof: 0 }
  const ohHelix = (ovhgId) => {
    for (const s of design.strands ?? []) {
      for (const d of s.domains ?? []) {
        if (d.overhang_id === ovhgId) return d.helix_id
      }
    }
    return null
  }
  const owningClusterId = (helixId) => {
    // Mirror of backend `_overhang_owning_cluster_id`: a cluster owns the
    // helix when either it's a helix-level cluster (no domain_ids), or every
    // strand domain on the helix is listed in cluster.domain_ids (full
    // coverage; no partial overlap). When MULTIPLE clusters own the helix
    // (caDNAno's auto-generated all-scaffold cluster + user-defined geometry
    // sub-clusters), the SMALLEST wins — the big convenience cluster is for
    // grouped transforms and shouldn't shadow the actual rigid sub-bodies.
    if (!helixId) return null
    const candidates = []   // { id, helixCount, idx }
    const transforms = design.cluster_transforms ?? []
    for (let idx = 0; idx < transforms.length; idx++) {
      const c = transforms[idx]
      if (!(c.helix_ids ?? []).includes(helixId)) continue
      const domIds = c.domain_ids ?? []
      if (domIds.length > 0) {
        const keys = new Set(domIds.map(dr => `${dr.strand_id}:${dr.domain_index}`))
        let anyUnmatched = false
        outer:
        for (const s of design.strands ?? []) {
          for (let di = 0; di < (s.domains ?? []).length; di++) {
            const d = s.domains[di]
            if (d.helix_id !== helixId) continue
            if (!keys.has(`${s.id}:${di}`)) { anyUnmatched = true; break outer }
          }
        }
        if (anyUnmatched) continue
      }
      candidates.push({ id: c.id, helixCount: (c.helix_ids ?? []).length, idx })
    }
    if (!candidates.length) return null
    // Smallest helix_count; tiebreak by later index (user-defined override).
    candidates.sort((a, b) => a.helixCount - b.helixCount || b.idx - a.idx)
    return candidates[0].id
  }
  const ca = owningClusterId(ohHelix(conn.overhang_a_id))
  const cb = owningClusterId(ohHelix(conn.overhang_b_id))
  if (ca == null && cb == null) {
    return { available: false, reason: "Neither overhang's helix is in a cluster.", n_dof: 0 }
  }
  if (ca === cb && ca != null) {
    return { available: false, reason: 'Both overhangs are on the same cluster — no joint separates them.', n_dof: 0 }
  }
  const joints = design.cluster_joints ?? []
  const jointIdsA = joints.filter(j => ca != null && j.cluster_id === ca).map(j => j.id)
  const jointIdsB = joints.filter(j => cb != null && j.cluster_id === cb).map(j => j.id)
  const jointIds = Array.from(new Set([...jointIdsA, ...jointIdsB]))   // dedupe in case ca === cb
  const n = jointIds.length
  if (n === 0) return { available: false, reason: 'No joints on either overhang’s cluster.', n_dof: 0, joint_ids: [] }
  // n >= 1 → relax is available. n === 1 runs the auto-pick path; n > 1
  // pops the joint-picker modal so the user chooses which joints to include.
  return { available: true, reason: '', n_dof: n, joint_ids: jointIds }
}

async function relaxLinker(connId, jointIds = null, configIndex = null) {
  try {
    await api.relaxLinker(connId, jointIds, { configIndex })
  } catch (err) {
    alert(`Could not relax linker: ${err?.message || err}`)
  }
}

/**
 * Open the interactive linker-config modal for an ss linker. The modal
 * lets the user crop the R_ee histogram with two draggable thumbs, pick
 * a snapshot, and optionally change the linker length, then Apply or
 * Cancel. Re-selecting "Relax linker" on an already-relaxed linker just
 * re-opens this modal (preserving the connection's current selection).
 */
async function _showSsLinkerConfigPicker(connId) {
  const design = store.getState().currentDesign
  const conn = design?.overhang_connections?.find(c => c.id === connId)
  if (!conn) return
  const { showLinkerConfigModal } = await import('../ui/linker_config_modal.js')
  showLinkerConfigModal({ conn })
}

/**
 * Show a small modal asking the user which joints to include in the relax
 * optimization. Used when the linker has more than 1 DOF — the user might
 * want to lock down some joints rather than freely vary all of them.
 *
 * `availableJointIds` are pre-filtered to joints on either overhang's owning
 * cluster (so each one CAN affect the chord). Defaults to all checked.
 */
function _showRelaxJointPicker(connId, availableJointIds) {
  const design = store.getState().currentDesign
  const allJoints = design?.cluster_joints ?? []
  const jointMap = new Map(allJoints.map(j => [j.id, j]))
  const clusterMap = new Map((design?.cluster_transforms ?? []).map(c => [c.id, c]))
  const available = availableJointIds.map(id => jointMap.get(id)).filter(Boolean)
  if (!available.length) {
    relaxLinker(connId)   // fall through; backend will reject if truly empty
    return
  }

  // Backdrop + dialog
  const backdrop = document.createElement('div')
  backdrop.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:10000;' +
    'display:flex;align-items:center;justify-content:center'
  const dialog = document.createElement('div')
  dialog.style.cssText =
    'background:#161b22;border:1px solid #30363d;border-radius:6px;' +
    'padding:14px 16px;min-width:280px;max-width:380px;' +
    'font-family:var(--font-ui);font-size:12px;color:#c9d1d9'

  const title = document.createElement('div')
  title.textContent = 'Relax Linker — choose joints'
  title.style.cssText = 'font-weight:bold;margin-bottom:6px;color:#e6edf3'
  dialog.appendChild(title)

  const sub = document.createElement('div')
  sub.textContent = `Optimize ${available.length} joint${available.length === 1 ? '' : 's'} so the linker chord matches its target length.`
  sub.style.cssText = 'color:#8b949e;margin-bottom:10px;font-size:11px'
  dialog.appendChild(sub)

  // Checkbox list
  const list = document.createElement('div')
  list.style.cssText = 'max-height:240px;overflow-y:auto;margin-bottom:12px'
  const checkboxes = []
  for (const j of available) {
    const row = document.createElement('label')
    row.style.cssText =
      'display:flex;align-items:center;gap:8px;padding:4px 6px;' +
      'border-radius:3px;cursor:pointer'
    row.addEventListener('mouseenter', () => row.style.background = '#1f262e')
    row.addEventListener('mouseleave', () => row.style.background = '')
    const cb = document.createElement('input')
    cb.type = 'checkbox'; cb.checked = true; cb.value = j.id
    cb.style.cssText = 'accent-color:#58a6ff'
    const lbl = document.createElement('span')
    const cluster = clusterMap.get(j.cluster_id)
    const cName = cluster?.name ?? j.cluster_id?.slice(0, 8) ?? '?'
    lbl.textContent = `${j.name || 'Joint'} — on ${cName}`
    row.appendChild(cb); row.appendChild(lbl)
    list.appendChild(row)
    checkboxes.push(cb)
  }
  dialog.appendChild(list)

  // Buttons
  const btnRow = document.createElement('div')
  btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px'
  const cancel = document.createElement('button')
  cancel.textContent = 'Cancel'
  cancel.style.cssText =
    'padding:5px 12px;background:#21262d;border:1px solid #30363d;' +
    'border-radius:4px;color:#c9d1d9;cursor:pointer;font-family:inherit;font-size:11px'
  cancel.addEventListener('click', () => document.body.removeChild(backdrop))
  const ok = document.createElement('button')
  ok.textContent = 'Relax'
  ok.style.cssText =
    'padding:5px 12px;background:#1f6feb;border:1px solid #1f6feb;' +
    'border-radius:4px;color:#fff;cursor:pointer;font-family:inherit;font-size:11px;font-weight:bold'
  ok.addEventListener('click', () => {
    const selected = checkboxes.filter(cb => cb.checked).map(cb => cb.value)
    document.body.removeChild(backdrop)
    if (!selected.length) return
    relaxLinker(connId, selected)
  })
  btnRow.appendChild(cancel); btnRow.appendChild(ok)
  dialog.appendChild(btnRow)

  backdrop.appendChild(dialog)
  backdrop.addEventListener('click', e => {
    if (e.target === backdrop) document.body.removeChild(backdrop)
  })
  document.body.appendChild(backdrop)
}

// ── Raycaster ─────────────────────────────────────────────────────────────────

const raycaster  = new THREE.Raycaster()
const _ndc       = new THREE.Vector2()
const _arcHitPx  = 18   // screen-space proximity threshold for crossover-arc hits (thin lines need a forgiving grab)

// ── Context menu ──────────────────────────────────────────────────────────────

let _menuEl = null


function _dismissMenu() {
  if (_menuEl) {
    _menuEl.remove()
    _menuEl = null
  }
}

function _menuOutsideListeners(menu) {
  // The menu is in the DOM by now, so its real size is measurable — re-fit it
  // inside the viewport (extends upward when right-clicked low on the screen).
  _placeMenu(menu)
  const onOutside = e => {
    if (!menu.contains(e.target)) {
      _dismissMenu()
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onEsc)
    }
  }
  const onEsc = e => {
    if (e.key === 'Escape') {
      _dismissMenu()
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onEsc)
    }
  }
  setTimeout(() => {
    document.addEventListener('pointerdown', onOutside)
    document.addEventListener('keydown', onEsc)
  }, 0)
}

function _menuBase(x, y) {
  const menu = document.createElement('div')
  menu.style.cssText = `
    position: fixed; left: ${x}px; top: ${y}px;
    background: #1e2a3a; border: 1px solid #3a4a5a; border-radius: 6px;
    padding: 4px 0; min-width: 110px; z-index: 9999;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5); font-family: var(--font-ui); font-size: 12px;
  `
  // Remember the requested anchor so _placeMenu() can re-fit after the items
  // are added and the real height is known.
  menu._anchorX = x
  menu._anchorY = y
  return menu
}

/**
 * Re-fit an already-appended context menu inside the viewport. Shifts left if it
 * would overflow the right edge, and **extends upward** (anchors its bottom near
 * the cursor) if it would overflow the bottom — so a menu right-clicked low on
 * the screen grows up instead of being clipped. If the menu is taller than the
 * whole viewport even when flipped, it gets a max-height + scrollbar.
 */
function _placeMenu(menu) {
  const margin = 8
  const x = menu._anchorX ?? 0
  const y = menu._anchorY ?? 0
  const rect = menu.getBoundingClientRect()
  const maxH = window.innerHeight - margin * 2

  let left = x
  if (left + rect.width > window.innerWidth) left = window.innerWidth - rect.width - margin
  if (left < margin) left = margin

  let top = y
  if (rect.height > maxH) {
    // Taller than the screen even when flipped — cap it and let it scroll.
    menu.style.maxHeight = `${maxH}px`
    menu.style.overflowY = 'auto'
    top = margin
  } else if (top + rect.height > window.innerHeight) {
    top = window.innerHeight - rect.height - margin
  }
  if (top < margin) top = margin

  menu.style.left = `${left}px`
  menu.style.top  = `${top}px`
}

function _menuItem(text, onClick, opts = {}) {
  const item = document.createElement('div')
  item.textContent = text
  const disabled = !!opts.disabled
  item.style.cssText = disabled
    ? `padding: 6px 14px; color: #6c7a8a; cursor: not-allowed;`
    : `padding: 6px 14px; color: #eef; cursor: pointer;`
  if (opts.title) item.title = opts.title
  if (!disabled) {
    item.addEventListener('mouseenter', () => { item.style.background = '#2a3a4a' })
    item.addEventListener('mouseleave', () => { item.style.background = 'transparent' })
    item.addEventListener('click', e => { e.stopPropagation(); _dismissMenu(); onClick() })
  } else {
    item.addEventListener('click', e => { e.stopPropagation() })
  }
  return item
}

/**
 * Append a "Representation" section to a right-click menu (mixed representation).
 * Pins a render rep onto the duplex region the selected strands/clusters cover
 * (BOTH strands, by column position), or resets it to the global rep. Stored as
 * positions so it survives break/crossover edits. Display-only.
 */
function _appendRepresentationMenu(menu, { strandIds = [], clusterIds = [], domainRefs = [] }) {
  if (!strandIds.length && !clusterIds.length && !domainRefs.length) return
  const apply = (rep) => {
    const design = store.getState().currentDesign
    let segs = []
    if (strandIds.length)  segs = segs.concat(strandsToSegments(design, strandIds))
    if (clusterIds.length) segs = segs.concat(clustersToSegments(design, clusterIds))
    if (domainRefs.length) segs = segs.concat(domainsToSegments(design, domainRefs))
    const next = editOverridesForSegments(design?.representation_overrides ?? [], segs, rep)
    api.saveRepresentationOverrides(next)
  }
  menu.appendChild(_menuSep())
  menu.appendChild(createRepresentationMenuItem({ apply, dismiss: _dismissMenu }))
}

function _menuSep() {
  const hr = document.createElement('div')
  hr.style.cssText = `border-top: 1px solid #3a4a5a; margin: 4px 0;`
  return hr
}

// ── Strand extension dialog ───────────────────────────────────────────────────

const MODIFICATION_NAMES = {
  cy3:     'Cy3',
  cy5:     'Cy5',
  fam:     'FAM',
  tamra:   'TAMRA',
  bhq1:    'BHQ-1',
  bhq2:    'BHQ-2',
  atto488: 'ATTO 488',
  atto550: 'ATTO 550',
  biotin:  'Biotin',
}

/**
 * Open the unified strand extension add/edit dialog.
 *
 * Applies the same sequence/modification/label to every supplied strand at the
 * chosen terminus (5′, 3′, or Both).  Uses the batch upsert endpoint so even
 * 100+ strands complete in a single round-trip.
 *
 * @param {number}   x                Screen X for positioning.
 * @param {number}   y                Screen Y for positioning.
 * @param {string[]} strandIds        Strand IDs to act on (≥1, staples only).
 * @param {Map<string,{five_prime:object|null, three_prime:object|null}>} existingsByStrand
 *   Maps strandId → existing extension records (null if absent).
 */
function _openExtensionDialog(x, y, strandIds, existingsByStrand) {
  _dismissMenu()
  document.getElementById('__ext-dialog')?.remove()

  const isSingle   = strandIds.length === 1
  const singleId   = isSingle ? strandIds[0] : null
  const singleExts = isSingle ? (existingsByStrand.get(singleId) ?? {}) : {}
  const hasAny     = [...existingsByStrand.values()].some(e => e.five_prime || e.three_prime)

  // Determine sensible default end selection for a single strand.
  // • If only one end exists: default to that end so the user edits in-place.
  // • If both exist, or multi-select: default to 'five_prime'.
  let defaultEnd = 'five_prime'
  if (isSingle) {
    if (singleExts.five_prime && !singleExts.three_prime) defaultEnd = 'five_prime'
    else if (singleExts.three_prime && !singleExts.five_prime) defaultEnd = 'three_prime'
    else if (singleExts.five_prime && singleExts.three_prime) defaultEnd = 'both'
  }

  // When editing a single strand with exactly one end, pre-fill those values.
  const prefill = (() => {
    if (!isSingle) return null
    if (defaultEnd === 'five_prime' && singleExts.five_prime) return singleExts.five_prime
    if (defaultEnd === 'three_prime' && singleExts.three_prime) return singleExts.three_prime
    return null
  })()

  const dlgW = 280
  const dlgH = 380
  const dlgX = Math.min(x + 8, window.innerWidth  - dlgW - 10)
  const dlgY = Math.min(y + 8, window.innerHeight - dlgH - 10)

  const dialog = document.createElement('div')
  dialog.id = '__ext-dialog'
  dialog.style.cssText = `
    position:fixed; left:${dlgX}px; top:${dlgY}px; width:${dlgW}px;
    background:#0d1117; border:1px solid #30363d; border-radius:8px; padding:14px 16px;
    z-index:10000; box-shadow:0 8px 24px rgba(0,0,0,.6);
    font-size:13px; color:#c9d1d9; user-select:none;
  `

  // Title
  const title = document.createElement('div')
  title.style.cssText = 'font-size:13px;font-weight:700;margin-bottom:10px;color:#cde'
  if (!hasAny) {
    title.textContent = strandIds.length > 1
      ? `Add extension to ${strandIds.length} strands`
      : 'Add extension'
  } else {
    title.textContent = strandIds.length > 1
      ? `Edit extensions on ${strandIds.length} strands`
      : 'Edit extensions'
  }
  dialog.appendChild(title)

  // End selector: 5′ | 3′ | Both
  let endVal = defaultEnd
  const endRow = document.createElement('div')
  endRow.style.cssText = 'display:flex;gap:12px;margin-bottom:10px'
  for (const [val, lbl] of [['five_prime', "5\u2032"], ['three_prime', "3\u2032"], ['both', 'Both']]) {
    const label = document.createElement('label')
    label.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;color:#cde;font-size:12px'
    const radio = document.createElement('input')
    radio.type = 'radio'; radio.name = '__ext-end'; radio.value = val
    if (val === defaultEnd) radio.checked = true
    radio.addEventListener('change', () => { endVal = val })
    label.appendChild(radio)
    label.appendChild(document.createTextNode(lbl))
    endRow.appendChild(label)
  }
  dialog.appendChild(endRow)

  // Sequence input
  const seqLabel = document.createElement('div')
  seqLabel.textContent = 'Sequence (ACGTN, optional):'
  seqLabel.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:4px'
  dialog.appendChild(seqLabel)

  const seqInput = document.createElement('input')
  seqInput.type = 'text'
  seqInput.value = prefill?.sequence ?? ''
  seqInput.placeholder = 'e.g. TTTT'
  seqInput.style.cssText = `
    width:100%;box-sizing:border-box;background:#161b22;border:1px solid #30363d;border-radius:4px;
    color:#c9d1d9;padding:5px 8px;font-family:var(--font-ui);font-size:12px;outline:none;margin-bottom:4px;
  `
  dialog.appendChild(seqInput)

  const seqHint = document.createElement('div')
  seqHint.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:8px;min-height:14px'
  dialog.appendChild(seqHint)

  seqInput.addEventListener('input', () => {
    const v = seqInput.value.trim().toUpperCase()
    if (v && !/^[ACGTN]+$/.test(v)) {
      seqHint.textContent = 'Only A, C, G, T, N allowed'
      seqHint.style.color = '#ff6b6b'
    } else {
      seqHint.textContent = v ? `${v.length} bp` : ''
      seqHint.style.color = '#8899aa'
    }
  })

  // Modification dropdown
  const modLabel = document.createElement('div')
  modLabel.textContent = 'Modification:'
  modLabel.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:4px'
  dialog.appendChild(modLabel)

  const modSel = document.createElement('select')
  modSel.style.cssText = `
    width:100%;background:#161b22;color:#c9d1d9;border:1px solid #30363d;
    border-radius:4px;padding:5px 6px;font-size:12px;cursor:pointer;outline:none;margin-bottom:8px;
  `
  const noneOpt = document.createElement('option')
  noneOpt.value = ''; noneOpt.textContent = 'None'
  modSel.appendChild(noneOpt)
  for (const [key, name] of Object.entries(MODIFICATION_NAMES)) {
    const opt = document.createElement('option')
    opt.value = key; opt.textContent = name
    modSel.appendChild(opt)
  }
  modSel.value = prefill?.modification ?? ''
  dialog.appendChild(modSel)

  // Label input
  const lblLabel = document.createElement('div')
  lblLabel.textContent = 'Label (optional):'
  lblLabel.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:4px'
  dialog.appendChild(lblLabel)

  const lblInput = document.createElement('input')
  lblInput.type = 'text'
  lblInput.value = prefill?.label ?? ''
  lblInput.placeholder = 'e.g. Cy3 dye'
  lblInput.style.cssText = `
    width:100%;box-sizing:border-box;background:#161b22;border:1px solid #30363d;border-radius:4px;
    color:#c9d1d9;padding:5px 8px;font-size:12px;outline:none;margin-bottom:10px;
  `
  dialog.appendChild(lblInput)

  // Error hint
  const errHint = document.createElement('div')
  errHint.style.cssText = 'font-size:11px;color:#ff6b6b;min-height:14px;margin-bottom:6px'
  dialog.appendChild(errHint)

  // Buttons
  const btns = document.createElement('div')
  btns.style.cssText = 'display:flex;gap:8px;justify-content:flex-end'

  const cancelBtn = document.createElement('button')
  cancelBtn.textContent = 'Cancel'
  cancelBtn.style.cssText = `
    background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;
    padding:5px 14px;cursor:pointer;font-size:12px;
  `
  cancelBtn.addEventListener('click', () => dialog.remove())

  const applyBtn = document.createElement('button')
  applyBtn.textContent = 'Apply'
  applyBtn.style.cssText = `
    background:#238636;border:1px solid #2ea043;color:#ffffff;border-radius:4px;
    padding:5px 14px;cursor:pointer;font-size:12px;
  `
  applyBtn.addEventListener('click', async () => {
    const seq = seqInput.value.trim().toUpperCase() || null
    const mod = modSel.value || null
    const lbl = lblInput.value.trim() || null

    if (!seq && !mod) {
      errHint.textContent = 'Provide at least a sequence or modification.'
      return
    }
    if (seq && !/^[ACGTN]+$/.test(seq)) {
      errHint.textContent = 'Sequence contains invalid characters.'
      return
    }

    // Build the list of (strandId, end) pairs to upsert.
    const ends = endVal === 'both' ? ['five_prime', 'three_prime'] : [endVal]
    const items = []
    for (const sid of strandIds) {
      for (const end of ends) {
        items.push({ strandId: sid, end, sequence: seq, modification: mod, label: lbl })
      }
    }

    applyBtn.disabled = true
    applyBtn.textContent = '\u2026'
    try {
      await api.upsertStrandExtensionsBatch(items)
      dialog.remove()
    } catch (err) {
      errHint.textContent = err?.message ?? 'Error saving extension.'
      applyBtn.disabled = false
      applyBtn.textContent = 'Apply'
    }
  })

  btns.appendChild(cancelBtn)
  btns.appendChild(applyBtn)
  dialog.appendChild(btns)
  document.body.appendChild(dialog)

  seqInput.focus()

  const _escListener = e => {
    if (e.key === 'Escape') { dialog.remove(); document.removeEventListener('keydown', _escListener) }
    if (e.key === 'Enter')  { applyBtn.click() }
  }
  document.addEventListener('keydown', _escListener)
  requestAnimationFrame(() => {
    const _outsideClick = e => {
      if (!dialog.contains(e.target)) { dialog.remove(); document.removeEventListener('mousedown', _outsideClick) }
    }
    document.addEventListener('mousedown', _outsideClick)
  })
}

function _showColorMenu(x, y, strandId, designRenderer, multiStrandIds = [], overhangOpts = null, ovhgMultiIds = null, onOpenOverhangsManager = null, domainRef = null) {
  _dismissMenu()
  const menu = _menuBase(x, y)
  const singleEffectiveIds = linkerComponentIds(strandId)
  const linkerConn = linkerConnectionForStrandId(strandId)

  // "Open Overhangs Manager…" — shown at top when 1–2 overhangs are selected
  // (e.g., via ctrl+click or lasso). Lets the user jump straight from a strand
  // right-click into the manager with the picked overhangs prepopulated.
  if (ovhgMultiIds && (ovhgMultiIds.length === 1 || ovhgMultiIds.length === 2) && onOpenOverhangsManager) {
    const label = ovhgMultiIds.length === 1
      ? 'Open Overhangs Manager (1 selected)…'
      : 'Open Overhangs Manager (2 selected)…'
    menu.appendChild(_menuItem(label, () => onOpenOverhangsManager(ovhgMultiIds)))
    menu.appendChild(_menuSep())
  }

  // Linker-specific actions at the top of the menu. Below this section the
  // standard strand-menu items (Isolate, Color, Group, Extensions, Delete)
  // continue to render — same UX as a normal staple, plus the linker section.
  if (linkerConn) {
    const linkerHdr = document.createElement('div')
    linkerHdr.textContent = `Linker · ${linkerLabel(linkerConn)}`
    linkerHdr.style.cssText = `
      padding: 3px 12px; color: #8899aa; font-size: 11px; letter-spacing: 0.05em;
      text-transform: uppercase; border-bottom: 1px solid #3a4a5a; margin-bottom: 4px;
    `
    menu.appendChild(linkerHdr)

    const design = store.getState().currentDesign
    const relax = _linkerRelaxStatus(design, linkerConn)
    const isSs = linkerConn.linker_type === 'ss'
    const relaxLabel = relax.n_dof > 1
      ? `Relax linker (${relax.n_dof} DOF)…`
      : (isSs ? 'Relax linker… (pick shape)' : 'Relax linker')
    const onRelax = () => {
      if (relax.n_dof > 1) _showRelaxJointPicker(linkerConn.id, relax.joint_ids)
      else if (isSs)       _showSsLinkerConfigPicker(linkerConn.id)
      else                 relaxLinker(linkerConn.id)
    }
    menu.appendChild(_menuItem(relaxLabel, onRelax, {
      disabled: !relax.available,
      title: relax.available
        ? (relax.n_dof > 1
            ? `Choose which of the ${relax.n_dof} joints to optimize.`
            : isSs
              ? 'Open the FJC shape picker (Rg / Rg ± σ).'
              : 'Optimize the joint angle so the linker’s connector arcs collapse.')
        : relax.reason,
    }))
    menu.appendChild(_menuSep())
  }

  // "Set overhang name" — shown at top when right-clicking an overhang domain
  if (overhangOpts?.overhangId && overhangOpts?.onSetName) {
    menu.appendChild(_menuItem('Set overhang name…', () => overhangOpts.onSetName(overhangOpts.overhangId)))
    menu.appendChild(_menuSep())
  }

  // Check if this strand is a scaffold
  const design = store.getState().currentDesign
  const _stype = design?.strands?.find(s => s.id === strandId)?.strand_type
  const isScaffold = _stype === 'scaffold'
  const isOhBinder = _stype === 'oh_binder'

  // Convert a scaffold-like strand into an OH binding strand (overhang-binding
  // oligo). Single strand only — links each domain to the overhang it pairs with.
  if (isScaffold && multiStrandIds.length === 0) {
    menu.appendChild(_menuItem(
      'Convert to OH binding strand',
      async () => { try { await api.convertStrandToBinder(strandId) } catch { /* lastError */ } },
      { title: 'Re-designate this strand as an overhang-binding oligo: link each domain to '
             + 'the overhang it antiparallel-pairs with (tagging the partner as an overhang '
             + 'if needed) and recolor it. Add a fluorophore afterward via "Add extension".' },
    ))
    menu.appendChild(_menuSep())
  }

  // Inverse: revert an OH binder back to scaffold.
  if (isOhBinder && multiStrandIds.length === 0) {
    menu.appendChild(_menuItem(
      'Convert to scaffold',
      async () => { try { await api.convertBinderToScaffold(strandId) } catch { /* lastError */ } },
      { title: 'Revert this overhang-binding oligo back to a scaffold strand: clear its '
             + 'binder links and remove any overhang the original conversion auto-created '
             + '(once nothing else binds it).' },
    ))
    menu.appendChild(_menuSep())
  }

  // Isolate / Un-isolate (only for non-scaffold strands)
  if (!isScaffold) {
    const { isolatedStrandId } = store.getState()
    const isIsolated = isolatedStrandId === strandId
    menu.appendChild(_menuItem(
      isIsolated ? 'Un-isolate' : 'Isolate',
      () => store.setState({ isolatedStrandId: isIsolated ? null : strandId }),
    ))
    menu.appendChild(_menuSep())
  }

  // Make Reference / Make Active — applies to any strand (incl. scaffold).
  {
    const refEffIds = multiStrandIds.length > 0
      ? [...new Set([...multiStrandIds, ...singleEffectiveIds])]
      : singleEffectiveIds
    const allRef = refEffIds.length > 0 &&
      refEffIds.every(id => design?.strands?.find(s => s.id === id)?.is_reference)
    menu.appendChild(_menuItem(
      allRef ? 'Make Active' : 'Make Reference',
      () => { api.patchStrandsReference(refEffIds, !allRef) },
      { title: 'Reference geometry is an inactive backdrop: ignored by all automatic '
             + 'features (bend/twist, sequence assignment, scaffold routing, autostaple, '
             + 'crossovers) and excluded from exports/validation, but still visible '
             + '(translucent) and manually editable. Use it to build off an existing part.' },
    ))
    menu.appendChild(_menuSep())
  }

  const header = document.createElement('div')
  header.textContent = 'Color'
  header.style.cssText = `
    padding: 3px 12px; color: #8899aa; font-size: 11px; letter-spacing: 0.05em;
    text-transform: uppercase; border-bottom: 1px solid #3a4a5a; margin-bottom: 4px;
  `
  menu.appendChild(header)

  const grid = document.createElement('div')
  grid.style.cssText = `display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; padding: 3px 8px;`
  for (const { hex, css, label } of PICKER_COLORS) {
    const swatch = document.createElement('div')
    swatch.title = label
    swatch.style.cssText = `
      width: 20px; height: 20px; border-radius: 3px; cursor: pointer;
      background: ${css}; border: 2px solid transparent; transition: border-color 0.1s;
    `
    swatch.addEventListener('mouseenter', () => { swatch.style.borderColor = '#ffffff' })
    swatch.addEventListener('mouseleave', () => { swatch.style.borderColor = 'transparent' })
    swatch.addEventListener('click', e => {
      e.stopPropagation()
      for (const sid of singleEffectiveIds) designRenderer.setStrandColor(sid, hex)
      api.patchStrandsColor(singleEffectiveIds, css)   // persist to backend so cadnano editor sees it
      _dismissMenu()
    })
    grid.appendChild(swatch)
  }
  menu.appendChild(grid)

  // Custom RGB color picker
  if (!isScaffold) {
    const rgbRow = document.createElement('div')
    rgbRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding:3px 8px 2px'
    const rgbLabel = document.createElement('span')
    rgbLabel.textContent = 'Custom'
    rgbLabel.style.cssText = 'color:#8899aa;font-size:11px'
    const rgbInput = document.createElement('input')
    rgbInput.type = 'color'
    rgbInput.value = '#ffffff'
    rgbInput.style.cssText = 'width:36px;height:22px;border:none;background:none;cursor:pointer;padding:0;border-radius:3px'
    rgbInput.addEventListener('change', e => {
      e.stopPropagation()
      const hex = parseInt(rgbInput.value.replace('#', ''), 16)
      for (const sid of singleEffectiveIds) designRenderer.setStrandColor(sid, hex)
      api.patchStrandsColor(singleEffectiveIds, rgbInput.value)   // persist to backend so cadnano editor sees it
      _dismissMenu()
    })
    rgbRow.appendChild(rgbLabel)
    rgbRow.appendChild(rgbInput)
    menu.appendChild(rgbRow)
  }

  // Groups section (non-scaffold only)
  if (!isScaffold) {
    menu.appendChild(_menuSep())
    const grpHeader = document.createElement('div')
    grpHeader.textContent = 'Group'
    grpHeader.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                               'text-transform:uppercase;border-bottom:1px solid #3a4a5a;margin-bottom:6px'
    menu.appendChild(grpHeader)

    const grpRow = document.createElement('div')
    grpRow.style.cssText = 'padding:0 10px 6px'

    const { strandGroups } = store.getState()
    const currentGroup = strandGroups.find(g => g.strandIds.includes(strandId))

    // If a multi-selection is active, include all of those strands too.
    const effectiveStrandIds = multiStrandIds.length > 0
      ? [...new Set([...multiStrandIds, ...singleEffectiveIds])]
      : singleEffectiveIds

    const sel = document.createElement('select')
    sel.style.cssText = 'width:100%;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;' +
                        'border-radius:4px;padding:3px 6px;font-size:12px;cursor:pointer;outline:none'
    sel.addEventListener('click', e => e.stopPropagation())

    const noneOpt = document.createElement('option')
    noneOpt.value       = ''
    noneOpt.textContent = '(no group)'
    sel.appendChild(noneOpt)

    for (const g of strandGroups) {
      const opt = document.createElement('option')
      opt.value       = g.id
      opt.textContent = g.name
      if (g.id === currentGroup?.id) opt.selected = true
      sel.appendChild(opt)
    }

    const newOpt = document.createElement('option')
    newOpt.value       = '__new__'
    newOpt.textContent = '＋ New group…'
    sel.appendChild(newOpt)

    if (!currentGroup) sel.value = ''

    // Inline name input — shown only when "＋ New group…" is chosen
    const newInput = document.createElement('input')
    newInput.type        = 'text'
    newInput.placeholder = 'Group name…'
    newInput.style.cssText = 'display:none;margin-top:5px;width:100%;box-sizing:border-box;' +
                              'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;' +
                              'border-radius:4px;padding:3px 6px;font-size:12px;outline:none'
    newInput.addEventListener('click', e => e.stopPropagation())

    function _applyGroupChange(groupId) {
      pushGroupUndo()
      const gs = store.getState().strandGroups
      // Remove all effective strands from every group, then add to chosen one.
      let updated = gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !effectiveStrandIds.includes(s)) }))
      if (groupId) {
        updated = updated.map(g =>
          g.id === groupId ? { ...g, strandIds: [...g.strandIds, ...effectiveStrandIds] } : g
        )
      }
      store.setState({ strandGroups: updated })
    }

    function _createAndAssign(name) {
      name = name.trim()
      if (!name) { sel.value = currentGroup?.id ?? ''; return }
      pushGroupUndo()
      const gs = store.getState().strandGroups
      const existing = gs.find(g => g.name === name)
      if (existing) {
        const updated = gs.map(g => ({
          ...g,
          strandIds: g.id === existing.id
            ? [...g.strandIds.filter(s => !effectiveStrandIds.includes(s)), ...effectiveStrandIds]
            : g.strandIds.filter(s => !effectiveStrandIds.includes(s)),
        }))
        store.setState({ strandGroups: updated })
      } else {
        const palette = ['#74b9ff','#6bcb77','#ff6b6b','#ffd93d','#a29bfe','#55efc4']
        const color   = palette[gs.length % palette.length]
        const newId   = `grp_${Date.now()}`
        let updated   = gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !effectiveStrandIds.includes(s)) }))
        updated = [...updated, { id: newId, name, color, strandIds: effectiveStrandIds }]
        store.setState({ strandGroups: updated })
      }
      _dismissMenu()
    }

    sel.addEventListener('change', e => {
      e.stopPropagation()
      if (sel.value === '__new__') {
        newInput.style.display = 'block'
        newInput.value = ''
        newInput.focus()
      } else {
        newInput.style.display = 'none'
        _applyGroupChange(sel.value)
        _dismissMenu()
      }
    })

    newInput.addEventListener('keydown', e => {
      e.stopPropagation()
      if (e.key === 'Enter')  { _createAndAssign(newInput.value) }
      if (e.key === 'Escape') { newInput.style.display = 'none'; sel.value = currentGroup?.id ?? '' }
    })
    newInput.addEventListener('blur', () => {
      if (newInput.style.display !== 'none') _createAndAssign(newInput.value)
    })

    grpRow.appendChild(sel)
    grpRow.appendChild(newInput)
    menu.appendChild(grpRow)
  }

  // Extensions (all strand types)
  {
    // Collect all strands affected: the right-clicked one plus any multi-selected ones.
    const effectiveIds = multiStrandIds.length > 0
      ? [...new Set([...multiStrandIds, strandId])]
      : [strandId]

    // Build existingsByStrand map for all affected strands.
    const existingsByStrand = new Map()
    for (const sid of effectiveIds) {
      existingsByStrand.set(sid, {
        five_prime:  (design?.extensions ?? []).find(e => e.strand_id === sid && e.end === 'five_prime')  ?? null,
        three_prime: (design?.extensions ?? []).find(e => e.strand_id === sid && e.end === 'three_prime') ?? null,
      })
    }

    const hasAnyExtension = [...existingsByStrand.values()].some(e => e.five_prime || e.three_prime)
    const allExtIds = [...existingsByStrand.values()]
      .flatMap(e => [e.five_prime?.id, e.three_prime?.id].filter(Boolean))

    menu.appendChild(_menuSep())

    const extLabel = hasAnyExtension ? 'Edit extensions\u2026' : 'Add extension\u2026'
    menu.appendChild(_menuItem(extLabel, () => {
      // Capture state into locals before _dismissMenu clears the menu.
      const ids  = effectiveIds.slice()
      const exts = new Map(existingsByStrand)
      _openExtensionDialog(x, y, ids, exts)
    }))

    if (hasAnyExtension) {
      const delExtItem = _menuItem('Remove extensions', async () => {
        const ids = allExtIds.slice()
        await api.deleteStrandExtensionsBatch(ids)
      })
      delExtItem.style.color = '#ff9999'
      menu.appendChild(delExtItem)
    }
  }

  // Representation override: scope to the single right-clicked DOMAIN when the
  // selection is at domain level, otherwise the whole strand(s).
  if (domainRef) {
    _appendRepresentationMenu(menu, { domainRefs: [domainRef] })
  } else if (strandId) {
    const repIds = multiStrandIds.length > 0
      ? [...new Set([...multiStrandIds, strandId])]
      : [strandId]
    _appendRepresentationMenu(menu, { strandIds: repIds })
  }

  // Delete (all strand types including scaffold). Linker strands are generated
  // from OverhangConnection records, so delete the connection rather than one
  // generated strand fragment.
  menu.appendChild(_menuSep())
  const delItem = linkerConn
    ? _menuItem('Delete entire linker', () => deleteEntireLinker(linkerConn.id))
    : _menuItem('Delete strand', () => api.deleteStrand(strandId))
  delItem.style.color = '#ff6b6b'
  menu.appendChild(delItem)

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

function _helixIdsFromStrandIds(strandIds, design) {
  const strandSet = new Set(strandIds)
  const helixSet  = new Set()
  for (const strand of design.strands ?? []) {
    if (!strandSet.has(strand.id)) continue
    for (const domain of strand.domains ?? []) helixSet.add(domain.helix_id)
  }
  return [...helixSet]
}

function _showMultiMenu(x, y, strandIds, designRenderer) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  // Header
  const hdr = document.createElement('div')
  hdr.textContent = `${strandIds.length} strand${strandIds.length === 1 ? '' : 's'} selected`
  hdr.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                      'border-bottom:1px solid #3a4a5a;margin-bottom:4px'
  menu.appendChild(hdr)

  // Make Reference / Make Active for the whole selection.
  {
    const design = store.getState().currentDesign
    const allRef = strandIds.length > 0 &&
      strandIds.every(id => design?.strands?.find(s => s.id === id)?.is_reference)
    const ids = strandIds.slice()
    menu.appendChild(_menuItem(
      allRef ? 'Make Active' : 'Make Reference',
      () => { api.patchStrandsReference(ids, !allRef) },
      { title: 'Reference geometry is an inactive backdrop: ignored by all automatic '
             + 'features (bend/twist, sequence assignment, scaffold routing, autostaple, '
             + 'crossovers) and excluded from exports/validation, but still visible '
             + '(translucent) and manually editable.' },
    ))
    menu.appendChild(_menuSep())
  }

  // Color all header
  const colorHdr = document.createElement('div')
  colorHdr.textContent = 'Color all'
  colorHdr.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                            'text-transform:uppercase;border-bottom:1px solid #3a4a5a;margin-bottom:4px'
  menu.appendChild(colorHdr)

  const grid = document.createElement('div')
  grid.style.cssText = 'display:grid;grid-template-columns:repeat(4,1fr);gap:4px;padding:3px 8px'
  for (const { hex, css, label } of PICKER_COLORS) {
    const sw = document.createElement('div')
    sw.title = label
    sw.style.cssText = `width:20px;height:20px;border-radius:3px;cursor:pointer;background:${css};border:2px solid transparent;transition:border-color .1s`
    sw.addEventListener('mouseenter', () => { sw.style.borderColor = '#fff' })
    sw.addEventListener('mouseleave', () => { sw.style.borderColor = 'transparent' })
    sw.addEventListener('click', e => {
      e.stopPropagation()
      for (const sid of strandIds) designRenderer.setStrandColor(sid, hex)
      api.patchStrandsColor(strandIds, css)   // persist to backend so cadnano editor sees it
      _dismissMenu()
    })
    grid.appendChild(sw)
  }
  menu.appendChild(grid)

  // Custom RGB
  const rgbRow = document.createElement('div')
  rgbRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding:3px 8px 2px'
  const rgbLabel = document.createElement('span')
  rgbLabel.textContent = 'Custom'
  rgbLabel.style.cssText = 'color:#8899aa;font-size:11px'
  const rgbInput = document.createElement('input')
  rgbInput.type = 'color'
  rgbInput.value = '#ffffff'
  rgbInput.style.cssText = 'width:36px;height:22px;border:none;background:none;cursor:pointer;padding:0;border-radius:3px'
  rgbInput.addEventListener('change', e => {
    e.stopPropagation()
    const hex = parseInt(rgbInput.value.replace('#', ''), 16)
    for (const sid of strandIds) designRenderer.setStrandColor(sid, hex)
    api.patchStrandsColor(strandIds, rgbInput.value)   // persist to backend so cadnano editor sees it
    _dismissMenu()
  })
  rgbRow.appendChild(rgbLabel)
  rgbRow.appendChild(rgbInput)
  menu.appendChild(rgbRow)

  // Groups
  menu.appendChild(_menuSep())
  const grpHdr = document.createElement('div')
  grpHdr.textContent = 'Groups'
  grpHdr.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                          'text-transform:uppercase;border-bottom:1px solid #3a4a5a;margin-bottom:4px'
  menu.appendChild(grpHdr)

  const multiGrpRow = document.createElement('div')
  multiGrpRow.style.cssText = 'padding:3px 8px;display:flex;gap:6px;align-items:center'

  const multiSel = document.createElement('select')
  multiSel.style.cssText = 'flex:1;background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                            'color:#c9d1d9;padding:3px 5px;font-size:11px;font-family:var(--font-ui)'
  const multiNone = document.createElement('option')
  multiNone.value = ''; multiNone.textContent = '— none —'
  multiSel.appendChild(multiNone)

  const { strandGroups: multiGroups } = store.getState()
  for (const g of multiGroups) {
    const opt = document.createElement('option')
    opt.value = g.id
    const anyIn = strandIds.some(sid => g.strandIds.includes(sid))
    opt.textContent = (anyIn ? '✓ ' : '\u00a0\u00a0') + g.name
    multiSel.appendChild(opt)
  }
  const multiNewOpt = document.createElement('option')
  multiNewOpt.value = '__new__'; multiNewOpt.textContent = '＋ New group…'
  multiSel.appendChild(multiNewOpt)

  const multiNewInput = document.createElement('input')
  multiNewInput.type = 'text'; multiNewInput.placeholder = 'Group name…'
  multiNewInput.style.cssText = 'display:none;flex:1;background:#0d1117;border:1px solid #30363d;' +
                                 'border-radius:4px;color:#c9d1d9;padding:3px 5px;font-size:11px;font-family:var(--font-ui)'

  function _multiApplyGroup(groupId) {
    pushGroupUndo()
    const gs = store.getState().strandGroups
    const target = gs.find(g => g.id === groupId)
    store.setState({
      strandGroups: gs.map(g => {
        if (g.id !== groupId) return { ...g, strandIds: g.strandIds.filter(s => !strandIds.includes(s)) }
        return { ...g, strandIds: [...new Set([...g.strandIds, ...strandIds])] }
      }),
    })
    // Persist the group color to each strand on the backend so it survives group removal.
    if (target?.color) {
      for (const sid of strandIds) api.patchStrand(sid, { color: target.color })
    }
    _dismissMenu()
  }

  function _multiCreateAndAssign(name) {
    name = name.trim()
    if (!name) { multiNewInput.style.display = 'none'; multiSel.style.display = ''; return }
    pushGroupUndo()
    const gs = store.getState().strandGroups
    // Check if a group with this name already exists — if so, join it.
    const existing = gs.find(g => g.name === name)
    if (existing) {
      _multiApplyGroup(existing.id)
      return
    }
    const palette = ['#74b9ff','#6bcb77','#ff6b6b','#ffd93d','#a29bfe','#55efc4']
    const color   = palette[gs.length % palette.length]
    const newGroup = { id: `grp_${Date.now()}`, name, color, strandIds: [...strandIds] }
    store.setState({
      strandGroups: [...gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !strandIds.includes(s)) })), newGroup],
    })
    // Persist the new group color to each strand on the backend.
    for (const sid of strandIds) api.patchStrand(sid, { color })
    _dismissMenu()
  }

  multiSel.addEventListener('change', e => {
    e.stopPropagation()
    if (multiSel.value === '__new__') {
      multiSel.style.display = 'none'
      multiNewInput.style.display = ''
      multiNewInput.focus()
    } else if (multiSel.value === '') {
      // remove from all groups
      pushGroupUndo()
      const gs = store.getState().strandGroups
      store.setState({ strandGroups: gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !strandIds.includes(s)) })) })
      _dismissMenu()
    } else {
      _multiApplyGroup(multiSel.value)
    }
  })

  multiNewInput.addEventListener('keydown', e => {
    e.stopPropagation()
    if (e.key === 'Enter')  _multiCreateAndAssign(multiNewInput.value)
    if (e.key === 'Escape') { multiNewInput.style.display = 'none'; multiSel.style.display = ''; multiSel.value = '' }
  })
  multiNewInput.addEventListener('blur', () => {
    if (multiNewInput.style.display !== 'none') _multiCreateAndAssign(multiNewInput.value)
  })

  multiGrpRow.appendChild(multiSel)
  multiGrpRow.appendChild(multiNewInput)
  menu.appendChild(multiGrpRow)

  // Clusters
  menu.appendChild(_menuSep())
  const clusterHdr = document.createElement('div')
  clusterHdr.textContent = 'Clusters'
  clusterHdr.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                              'text-transform:uppercase;border-bottom:1px solid #3a4a5a;margin-bottom:4px'
  menu.appendChild(clusterHdr)

  const clusterRow = document.createElement('div')
  clusterRow.style.cssText = 'padding:3px 8px;display:flex;gap:6px;align-items:center'

  const clusterSel = document.createElement('select')
  clusterSel.style.cssText = 'flex:1;background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                              'color:#c9d1d9;padding:3px 5px;font-size:11px;font-family:var(--font-ui)'
  const clusterNoneOpt = document.createElement('option')
  clusterNoneOpt.value = ''; clusterNoneOpt.textContent = '— none —'
  clusterSel.appendChild(clusterNoneOpt)

  const { currentDesign } = store.getState()
  const clusterList = currentDesign?.cluster_transforms ?? []
  for (const c of clusterList) {
    const opt = document.createElement('option')
    opt.value = c.id
    opt.textContent = c.name
    clusterSel.appendChild(opt)
  }
  const clusterNewOpt = document.createElement('option')
  clusterNewOpt.value = '__new__'; clusterNewOpt.textContent = '＋ New cluster…'
  clusterSel.appendChild(clusterNewOpt)

  clusterSel.addEventListener('change', async e => {
    e.stopPropagation()
    const design = store.getState().currentDesign
    if (!design) return
    const helixIds = _helixIdsFromStrandIds(strandIds, design)
    if (!helixIds.length) { clusterSel.value = ''; return }

    if (clusterSel.value === '__new__') {
      const n = (design.cluster_transforms?.length ?? 0) + 1
      await api.createCluster({ name: `Cluster ${n}`, helix_ids: helixIds })
      _dismissMenu()
    } else if (clusterSel.value) {
      const clusterId = clusterSel.value
      const existing = design.cluster_transforms?.find(c => c.id === clusterId)
      if (existing) {
        const merged = [...new Set([...existing.helix_ids, ...helixIds])]
        await api.patchCluster(clusterId, { helix_ids: merged })
      }
      _dismissMenu()
    }
  })

  clusterRow.appendChild(clusterSel)
  menu.appendChild(clusterRow)

  // Extensions (all strand types)
  const design = store.getState().currentDesign
  if (strandIds.length > 0) {
    const existingsByStrand = new Map()
    for (const sid of strandIds) {
      existingsByStrand.set(sid, {
        five_prime:  (design?.extensions ?? []).find(e => e.strand_id === sid && e.end === 'five_prime')  ?? null,
        three_prime: (design?.extensions ?? []).find(e => e.strand_id === sid && e.end === 'three_prime') ?? null,
      })
    }
    const hasAnyExtension = [...existingsByStrand.values()].some(e => e.five_prime || e.three_prime)
    const allExtIds = [...existingsByStrand.values()]
      .flatMap(e => [e.five_prime?.id, e.three_prime?.id].filter(Boolean))

    menu.appendChild(_menuSep())
    const extLabel = hasAnyExtension ? 'Edit extensions\u2026' : 'Add extension\u2026'
    menu.appendChild(_menuItem(extLabel, () => {
      const ids  = strandIds.slice()
      const exts = new Map(existingsByStrand)
      _openExtensionDialog(x, y, ids, exts)
    }))
    if (hasAnyExtension) {
      const delExtItem = _menuItem('Remove extensions', async () => {
        await api.deleteStrandExtensionsBatch(allExtIds.slice())
      })
      delExtItem.style.color = '#ff9999'
      menu.appendChild(delExtItem)
    }
  }

  // Representation override for all selected strands.
  _appendRepresentationMenu(menu, { strandIds: strandIds.slice() })

  // Delete all
  menu.appendChild(_menuSep())
  const delItem = _menuItem(`Delete ${strandIds.length} strand${strandIds.length === 1 ? '' : 's'}`, async () => {
    if (strandIds.length === 1) await api.deleteStrand(strandIds[0])
    else await api.deleteStrandsBatch(strandIds.slice())
  })
  delItem.style.color = '#ff6b6b'
  menu.appendChild(delItem)

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

function _showNickMenu(x, y, coneEntry, onNick) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  const item = document.createElement('div')
  item.textContent = 'Nick here'
  item.style.cssText = `padding: 6px 14px; color: #eef; cursor: pointer;`
  item.addEventListener('mouseenter', () => { item.style.background = '#2a3a4a' })
  item.addEventListener('mouseleave', () => { item.style.background = 'transparent' })
  item.addEventListener('click', e => {
    e.stopPropagation()
    _dismissMenu()
    const { helix_id, bp_index, direction } = coneEntry.fromNuc
    onNick?.({ helixId: helix_id, bpIndex: bp_index, direction })
  })
  menu.appendChild(item)

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

function _showLoopSkipMenu(x, y, nuc, onLoopSkip) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  const { helix_id, bp_index } = nuc

  // Check if there's an existing loop/skip at this position
  const design = store.getState().currentDesign
  const helix  = design?.helices?.find(h => h.id === helix_id)
  const existing = helix?.loop_skips?.find(ls => ls.bp_index === bp_index)

  if (existing) {
    menu.appendChild(_menuItem(
      existing.delta === 1 ? 'Remove loop' : 'Remove skip',
      () => onLoopSkip?.({ helixId: helix_id, bpIndex: bp_index, delta: 0 }),
    ))
    menu.appendChild(_menuSep())
  }

  menu.appendChild(_menuItem(
    'Add loop (+1 bp)',
    () => onLoopSkip?.({ helixId: helix_id, bpIndex: bp_index, delta: 1 }),
  ))
  menu.appendChild(_menuItem(
    'Add skip (−1 bp)',
    () => onLoopSkip?.({ helixId: helix_id, bpIndex: bp_index, delta: -1 }),
  ))

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

// Flexible ssDNA segment menu — mark/unmark the contiguous unpaired run
// containing the clicked bead as a flexible tether, or clear all. Gated to
// unpaired beads (nuc.is_unpaired) by the caller. onFlexibleSegmentRightClick(
// nuc, action) is handled in main.js (computes the run + calls the client API).
function _showFlexibleSegmentMenu(x, y, nuc, onFlexibleSegmentRightClick) {
  _dismissMenu()
  const menu = _menuBase(x, y)
  const design = store.getState().currentDesign
  const marks = design?.flexible_segment_marks ?? []
  const marked = marks.some(m =>
    m.strand_id === nuc.strand_id && m.domain_index === nuc.domain_index &&
    m.bp_index === nuc.bp_index && m.direction === nuc.direction)

  if (marked) {
    const rm = _menuItem('Unmark flexible segment', () => onFlexibleSegmentRightClick?.(nuc, 'unmark'))
    rm.style.color = '#ff6b6b'
    menu.appendChild(rm)
  } else {
    menu.appendChild(_menuItem('Mark flexible segment', () => onFlexibleSegmentRightClick?.(nuc, 'mark')))
  }
  if (marked) {
    menu.appendChild(_menuSep())
    menu.appendChild(_menuItem('Relax this segment', () => onFlexibleSegmentRightClick?.(nuc, 'relax_one')))
    menu.appendChild(_menuItem('Relax all flexible segments', () => onFlexibleSegmentRightClick?.(nuc, 'relax_all')))
  }
  if (marks.length > 0) {
    menu.appendChild(_menuSep())
    const clear = _menuItem('Clear all flexible segments', () => onFlexibleSegmentRightClick?.(nuc, 'clear'))
    clear.style.color = '#ff6b6b'
    menu.appendChild(clear)
  }

  // Representation override for the flexible region's domain.
  if (nuc?.strand_id != null && nuc?.domain_index != null) {
    _appendRepresentationMenu(menu, { domainRefs: [{ strandId: nuc.strand_id, domainIndex: nuc.domain_index }] })
  }

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

// Right-click on a rendered flexible arc (bowed bead/tube, connection `connId`)
// → unmark that whole segment, or clear all.
function _showFlexibleConnectionMenu(x, y, connId, onFlexibleSegmentRightClick) {
  _dismissMenu()
  const menu = _menuBase(x, y)
  menu.appendChild(_menuItem('Relax this segment', () => onFlexibleSegmentRightClick?.(null, 'relax_one', connId)))
  menu.appendChild(_menuItem('Relax all flexible segments', () => onFlexibleSegmentRightClick?.(null, 'relax_all')))
  menu.appendChild(_menuSep())
  const rm = _menuItem('Unmark as flexible', () => onFlexibleSegmentRightClick?.(null, 'unmark_connection', connId))
  rm.style.color = '#ff6b6b'
  menu.appendChild(rm)
  menu.appendChild(_menuSep())
  menu.appendChild(_menuItem('Clear all flexible segments', () => onFlexibleSegmentRightClick?.(null, 'clear')))
  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

// Right-click on a selected cluster (drill `_mode === 'cluster'`) → offer the
// move/rotate gizmo for that cluster. Mirrors the assembly part-instance menu's
// "Move / Rotate" entry; the callback owns gizmo attachment in main.js.
function _showClusterMenu(x, y, clusterId, onClusterMoveRotate) {
  _dismissMenu()
  const menu = _menuBase(x, y)
  const design = store.getState().currentDesign
  const cluster = design?.cluster_transforms?.find(c => c.id === clusterId)
  const name = cluster?.name || clusterId?.slice(0, 8) || 'cluster'

  const hdr = document.createElement('div')
  hdr.textContent = name
  hdr.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
    'text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'
  menu.appendChild(hdr)

  menu.appendChild(_menuItem('Move / Rotate', () => onClusterMoveRotate?.(clusterId)))

  // Representation override for this cluster's region.
  _appendRepresentationMenu(menu, { clusterIds: [clusterId] })

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

function _showCrossoverMenu(x, y, xo, onCrossoverRightClick) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  const hasExtra = !!xo.extra_bases
  const label = hasExtra ? 'Edit extra bases…' : 'Add extra bases…'
  menu.appendChild(_menuItem(label, () => onCrossoverRightClick?.(xo, 'extra_bases')))

  if (hasExtra) {
    const removeItem = _menuItem('Remove extra bases', () => onCrossoverRightClick?.(xo, 'remove_extra_bases'))
    removeItem.style.color = '#ff6b6b'
    menu.appendChild(removeItem)
  }

  // ── Generic Relax Bond — closes a stretched crossover/ligation chord via
  // cluster transforms. Distinguishes Crossover vs ForcedLigation by
  // schema shape (Crossover has `half_a`/`half_b`; ForcedLigation has
  // `three_prime_*` / `five_prime_*`). In the 0-DOF case the user picks
  // which cluster moves via two menu items.
  const design = store.getState().currentDesign
  const isCrossover = xo && xo.half_a != null && xo.half_b != null
  const isLigation  = xo && xo.three_prime_helix_id != null
  if (design && (isCrossover || isLigation)) {
    const helixA = isCrossover ? xo.half_a.helix_id  : xo.three_prime_helix_id
    const helixB = isCrossover ? xo.half_b.helix_id  : xo.five_prime_helix_id
    // Pair-pick across overlapping cluster memberships. _autodetect_clusters
    // produces a scaffold cluster that wraps a whole scaffold AND geometry
    // sub-clusters; first-match would always return the scaffold cluster for
    // both halves of any forced scaffold ligation and hide the relax items.
    // Backend mirrors this via `_cluster_pair_for_bond_relax`.
    const cts = design.cluster_transforms ?? []
    const membersA = cts.filter(c => (c.helix_ids ?? []).includes(helixA))
    const membersB = cts.filter(c => (c.helix_ids ?? []).includes(helixB))
    let clusterA = null, clusterB = null
    for (const a of membersA) {
      for (const b of membersB) {
        if (a.id !== b.id) { clusterA = a; clusterB = b; break }
      }
      if (clusterA) break
    }
    if (clusterA && clusterB) {
      const jointsBetween = (design.cluster_joints ?? [])
        .filter(j => j.cluster_id === clusterA.id || j.cluster_id === clusterB.id)
      const bondType = isCrossover ? 'crossover' : 'ligation'
      const bondRef  = { bond_type: bondType, bond_id: xo.id }
      // Separator before the relax block.
      const sep = document.createElement('div')
      sep.style.cssText = 'height:1px;background:#30363d;margin:4px 0'
      menu.appendChild(sep)
      if (jointsBetween.length === 0) {
        // 0-DOF — user picks which cluster translates.
        const labelA = `Relax bond — move ${clusterA.name || clusterA.id.slice(0, 6)}`
        const labelB = `Relax bond — move ${clusterB.name || clusterB.id.slice(0, 6)}`
        menu.appendChild(_menuItem(labelA, async () => {
          try { await api.relaxBond(bondRef, { sideToMove: 'a' }) }
          catch (err) { console.warn('[relax-bond a]', err) }
        }))
        menu.appendChild(_menuItem(labelB, async () => {
          try { await api.relaxBond(bondRef, { sideToMove: 'b' }) }
          catch (err) { console.warn('[relax-bond b]', err) }
        }))
      } else {
        // 1-DOF / N-DOF — joint optimisation auto-picks all joints between.
        const dofLabel = jointsBetween.length === 1
          ? 'Relax bond (1 DOF)'
          : `Relax bond (${jointsBetween.length} DOF)`
        menu.appendChild(_menuItem(dofLabel, async () => {
          try { await api.relaxBond(bondRef, {}) }
          catch (err) { console.warn('[relax-bond joint]', err) }
        }))
      }
    }
  }

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

// ── Main initialiser ──────────────────────────────────────────────────────────

/**
 * @param {HTMLCanvasElement} canvas
 * @param {THREE.Camera} camera
 * @param {object} designRenderer
 * @param {{ onNick?: Function, onLoopSkip?: Function, onOverhangArrow?: Function, onScaffoldRightClick?: Function, getUnfoldView?: () => object, getOverhangLocations?: () => object, getLoopSkipHighlight?: () => object, controls?: object }} [opts]
 */
export function initSelectionManager(canvas, camera, designRenderer, opts = {}) {
  const { onNick, onLoopSkip, onOverhangArrow, onScaffoldRightClick, onCrossoverRightClick, onFlexibleSegmentRightClick, onSetOverhangName, onOverhangRightClick, onOpenOverhangsManager, onEmptyContextMenu, onClusterMoveRotate, getUnfoldView, getOverhangLocations, getOverhangLinkArcs, getFlexibleArcs, getLoopSkipHighlight, controls, getHoverEntry, getCamera, isDisabled, getProteinRenderer, getRegionVdwRenderer, getRegionBallstickRenderer, getRegionSurfaceRenderer, isManualSelect, onDrillLevel, drillV2 = isDrillV2() } = opts

  // Use the active render camera (ortho in cadnano mode, perspective otherwise).
  const _cam = () => getCamera?.() ?? camera

  // ── State ────────────────────────────────────────────────────────────────
  let _mode            = 'none'   // 'none' | 'strand' | 'domain' | 'bead' | 'cone' | 'cylinder'
  let _strandId        = null
  let _domainIndex     = null     // domain_index of selected domain (domain/bead modes)
  let _beadEntry       = null
  let _coneEntry       = null
  let _strandEntries     = []     // backbone entries for selected strand
  let _strandConeEntries = []     // cone entries for selected strand
  let _strandArcEntries  = []     // arc entries for selected strand
  let _xoverHighlightId  = null   // strand_id whose xover beads are currently scaled up
  let _cylStrandId       = null   // strand selected via cylinder LOD hit
  let _crossoverId       = null   // crossover id when in 'crossover' selection mode

  // ── Auto-drill state ───────────────────────────────────────────────────────
  // Repeated clicks on the same "section" descend cluster → strand → domain →
  // bead (or → xover for a cone), then cycle back to cluster. Active only in
  // auto-drill mode (isManualSelect() === false). _drillAnchor identifies the
  // section as `${strandId}:${kind}` where kind is 'bead' or 'cone'; a click on
  // a different anchor restarts the drill at the cluster level.
  let _drillAnchor    = null
  let _drillLevel     = 0
  let _drillSeq       = []
  let _drillClusterId = null
  // Tab drill-lock: when set ('cluster'|'strand'|'domain'|'bead'|'xover'), the
  // auto-drill stops cycling and every click selects at this FIXED level instead.
  // null = normal descend-on-repeat-click behaviour.
  let _drillLock      = null

  // ── Drill v2 (ISSUE-4 Phase 2) ─────────────────────────────────────────────
  // One unified `selectionLevel` replaces the auto-drill ladder + manual pins +
  // Tab-lock when the NADOC_DRILL_V2 flag is on. See scene/selection_level.js.
  const _drillV2 = !!drillV2
  let _selLevel  = 'default'   // 'default' | 'cluster' | 'domain' | 'end' | 'xover'
  // Hover-preview affordance (default level, strand selected): the bead/cone under
  // the cursor previews the leaf a 2nd click would select.
  let _hoverBead = null
  let _hoverCone = null
  let _hoverArc  = null

  function _autoDrill() { return !isManualSelect?.() }

  function _resetDrill() {
    _drillAnchor    = null
    _drillLevel     = 0
    _drillSeq       = []
    _drillClusterId = null
  }

  function _emitDrillLevel(level) { onDrillLevel?.(level) }

  function _currentDrillType() {
    if (!_autoDrill() || !_drillSeq.length) return null
    return _drillSeq[_drillLevel]
  }

  // Smallest non-default cluster containing the nuc; falls back to the default
  // (all-helices) cluster, then any containing cluster. Mirrors the bridge/
  // exclusive membership split via clusterMemberFilter (shared with the gizmo).
  function _resolveClusterId(nuc, design) {
    const cts = design?.cluster_transforms ?? []
    if (!cts.length) return null
    let best = null, bestSize = Infinity
    for (const c of cts) {
      if (c.is_default) continue
      const f = clusterMemberFilter(c, design)
      if (f && f(nuc)) {
        const size = c.helix_ids?.length ?? Infinity
        if (size < bestSize) { best = c; bestSize = size }
      }
    }
    if (best) return best.id
    const def = cts.find(c => c.is_default && clusterMemberFilter(c, design)?.(nuc))
    if (def) return def.id
    const any = cts.find(c => clusterMemberFilter(c, design)?.(nuc))
    return any?.id ?? null
  }

  function _clusterEntries(clusterId, design, backboneEntries) {
    const cluster = design?.cluster_transforms?.find(c => c.id === clusterId)
    const f = cluster ? clusterMemberFilter(cluster, design) : null
    if (!f) return []
    return backboneEntries.filter(e => f(e.nuc))
  }

  function _clusterSelection(clusterId) {
    const design = store.getState().currentDesign
    const c = design?.cluster_transforms?.find(c => c.id === clusterId)
    return {
      type: 'cluster',
      id:   clusterId,
      data: { cluster_id: clusterId, helix_ids: c?.helix_ids ?? [], is_default: !!c?.is_default },
    }
  }

  function _highlightCluster(clusterId, backboneEntries) {
    _restoreStrand()
    const design  = store.getState().currentDesign
    const entries = _clusterEntries(clusterId, design, backboneEntries)
    // Reuse the strand-entry slot so _restoreStrand cleans up the cluster glow.
    _strandEntries = entries
    for (const e of entries) designRenderer.setBeadScale(e, 1.3)
    _setSelectionGlow(entries)
    _drillClusterId = clusterId
  }

  // Bead-hit auto-drill: cluster → strand → domain → bead, cycling. The clicked
  // bead's domain/identity drives the deeper levels; the cluster level uses the
  // smallest cluster that contains the bead.
  function _autoDrillBead(hitEntry, hitStrandId, backboneEntries, coneEntries) {
    const design = store.getState().currentDesign
    const anchor = `${hitStrandId}:bead`
    // Cap the drill by what this column actually renders as: cylinders → domain
    // (no visible bead); surface → strand (no per-bp attribution); full/vdw/ballstick
    // → down to the nucleotide (beads or atoms are visible there).
    const _rep = designRenderer.columnRepAt?.(hitEntry.nuc.helix_id, hitEntry.nuc.bp_index)
    _drillSeq = _rep === 'cylinders' ? ['cluster', 'strand', 'domain']
              : _rep === 'surface'   ? ['cluster', 'strand']
              : ['cluster', 'strand', 'domain', 'bead']
    if (_drillLock) {
      const i = _drillSeq.indexOf(_drillLock)
      _drillLevel = i >= 0 ? i : 1   // a lock not on this sequence (xover) → strand
      _drillAnchor = anchor
    } else if (_drillAnchor === anchor) {
      _drillLevel = (_drillLevel + 1) % _drillSeq.length
    } else {
      _drillAnchor = anchor; _drillLevel = 0
    }
    let level = _drillSeq[_drillLevel]

    if (level === 'cluster') {
      const cid = _resolveClusterId(hitEntry.nuc, design)
      if (cid) {
        _mode = 'cluster'; _strandId = hitStrandId
        _highlightCluster(cid, backboneEntries)
        store.setState({ selectedObject: _clusterSelection(cid) })
        _emitDrillLevel('cluster')
        return
      }
      // No cluster contains this bead → skip straight to strand.
      _drillLevel = 1; level = 'strand'
    }

    if (level === 'strand') {
      _mode = 'strand'; _strandId = hitStrandId; _coneEntry = null
      _highlightStrand(backboneEntries, coneEntries, hitStrandId)
      store.setState({ selectedObject: _strandSelection(hitStrandId, { helix_id: hitEntry.nuc.helix_id }) })
    } else if (level === 'domain') {
      const domainIdx = hitEntry.nuc.domain_index ?? 0
      _mode = 'domain'; _strandId = hitStrandId
      _highlightStrand(backboneEntries, coneEntries, hitStrandId)
      _highlightDomain(domainIdx)
      const domainObj = design?.strands?.find(s => s.id === hitStrandId)?.domains?.[domainIdx]
      store.setState({
        selectedObject: {
          type: 'domain',
          id:   `${hitStrandId}:${domainIdx}`,
          data: {
            strand_id:    hitStrandId,
            domain_index: domainIdx,
            helix_id:     domainObj?.helix_id    ?? hitEntry.nuc.helix_id,
            direction:    domainObj?.direction   ?? hitEntry.nuc.direction,
            overhang_id:  domainObj?.overhang_id ?? null,
          },
        },
      })
    } else {  // 'bead'
      _mode = 'bead'; _strandId = hitStrandId
      _highlightStrand(backboneEntries, coneEntries, hitStrandId)
      _highlightBead(hitEntry)
      store.setState({
        selectedObject: {
          type: 'nucleotide',
          id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
          data: hitEntry.nuc,
        },
      })
    }
    _emitDrillLevel(level)
  }

  // Cone-hit auto-drill: cluster → strand → xover (the cone is the leaf).
  function _autoDrillCone(hitCone, hitStrandId, backboneEntries, coneEntries) {
    const design = store.getState().currentDesign
    const anchor = `${hitStrandId}:cone`
    _drillSeq = ['cluster', 'strand', 'xover']
    if (_drillLock) {
      const i = _drillSeq.indexOf(_drillLock)
      _drillLevel = i >= 0 ? i : 1   // a lock not on this sequence (domain/bead) → strand
      _drillAnchor = anchor
    } else if (_drillAnchor === anchor) {
      _drillLevel = (_drillLevel + 1) % _drillSeq.length
    } else {
      _drillAnchor = anchor; _drillLevel = 0
    }
    let level = _drillSeq[_drillLevel]

    if (level === 'cluster') {
      const repNuc = hitCone.fromNuc ?? hitCone.toNuc
      const cid = repNuc ? _resolveClusterId(repNuc, design) : null
      if (cid) {
        _mode = 'cluster'; _strandId = hitStrandId
        _highlightCluster(cid, backboneEntries)
        store.setState({ selectedObject: _clusterSelection(cid) })
        _emitDrillLevel('cluster')
        return
      }
      _drillLevel = 1; level = 'strand'
    }

    if (level === 'strand') {
      _mode = 'strand'; _strandId = hitStrandId
      _highlightStrand(backboneEntries, coneEntries, hitStrandId)
      store.setState({ selectedObject: _strandSelection(hitStrandId) })
    } else {  // 'xover'
      _highlightStrand(backboneEntries, coneEntries, hitStrandId)
      _mode = 'cone'; _strandId = hitStrandId
      _highlightCone(hitCone)
      const { fromNuc, toNuc } = hitCone
      store.setState({
        selectedObject: {
          type: 'cone',
          id:   `${fromNuc.helix_id}:${fromNuc.bp_index}:${fromNuc.direction}→${toNuc.helix_id}:${toNuc.bp_index}:${toNuc.direction}`,
          data: { fromNuc, toNuc, strand_id: hitStrandId },
        },
      })
    }
    _emitDrillLevel(level)
  }

  // ── Drill v2 select primitives ─────────────────────────────────────────────
  // Small reusable selectors keyed by level; mirror the bodies inside the legacy
  // _autoDrill* functions but driven by the single _selLevel instead of a ladder.

  function _selectStrandV2(hitStrandId, hitEntry, backboneEntries, coneEntries) {
    _mode = 'strand'; _strandId = hitStrandId; _coneEntry = null
    _highlightStrand(backboneEntries, coneEntries, hitStrandId)
    store.setState({
      selectedObject: _strandSelection(hitStrandId, hitEntry ? { helix_id: hitEntry.nuc.helix_id } : {}),
    })
  }

  function _selectClusterV2(nuc, hitStrandId, backboneEntries) {
    const design = store.getState().currentDesign
    const cid = _resolveClusterId(nuc, design)
    if (!cid) return false
    _mode = 'cluster'; _strandId = hitStrandId
    _highlightCluster(cid, backboneEntries)
    store.setState({ selectedObject: _clusterSelection(cid) })
    return true
  }

  function _selectDomainV2(hitEntry, hitStrandId, backboneEntries, coneEntries) {
    const design = store.getState().currentDesign
    const domainIdx = hitEntry.nuc.domain_index ?? 0
    _mode = 'domain'; _strandId = hitStrandId
    _highlightStrand(backboneEntries, coneEntries, hitStrandId)
    _highlightDomain(domainIdx)
    const domainObj = design?.strands?.find(s => s.id === hitStrandId)?.domains?.[domainIdx]
    store.setState({
      selectedObject: {
        type: 'domain',
        id:   `${hitStrandId}:${domainIdx}`,
        data: {
          strand_id:    hitStrandId,
          domain_index: domainIdx,
          helix_id:     domainObj?.helix_id    ?? hitEntry.nuc.helix_id,
          direction:    domainObj?.direction   ?? hitEntry.nuc.direction,
          overhang_id:  domainObj?.overhang_id ?? null,
        },
      },
    })
  }

  function _selectBeadV2(hitEntry, hitStrandId, backboneEntries, coneEntries) {
    _mode = 'bead'; _strandId = hitStrandId
    _highlightStrand(backboneEntries, coneEntries, hitStrandId)
    _highlightBead(hitEntry)
    store.setState({
      selectedObject: {
        type: 'nucleotide',
        id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
        data: hitEntry.nuc,
      },
    })
  }

  function _selectConeV2(hitCone, hitStrandId, backboneEntries, coneEntries) {
    _highlightStrand(backboneEntries, coneEntries, hitStrandId)
    _mode = 'cone'; _strandId = hitStrandId
    _highlightCone(hitCone)
    const { fromNuc, toNuc } = hitCone
    store.setState({
      selectedObject: {
        type: 'cone',
        id:   `${fromNuc.helix_id}:${fromNuc.bp_index}:${fromNuc.direction}→${toNuc.helix_id}:${toNuc.bp_index}:${toNuc.direction}`,
        data: { fromNuc, toNuc, strand_id: hitStrandId },
      },
    })
  }

  // Drill-v2 bead-hit dispatch — fixed-level select, or strand→leaf-under-cursor
  // in default level. The leaf is the actually-clicked bead (an "end"); in
  // cylinders/surface columns there is no pickable bead, so the leaf falls back to
  // the domain (rep caveat). Returns true when handled.
  function _v2HandleBead(hitEntry, backboneEntries, coneEntries) {
    const hitStrandId = hitEntry.nuc.strand_id
    _clearHoverPreview()
    if (_selLevel === 'cluster') {
      if (!_selectClusterV2(hitEntry.nuc, hitStrandId, backboneEntries)) {
        _selectStrandV2(hitStrandId, hitEntry, backboneEntries, coneEntries)
      }
      _emitDrillLevel('cluster'); return
    }
    if (_selLevel === 'strand') {
      _selectStrandV2(hitStrandId, hitEntry, backboneEntries, coneEntries)
      _emitDrillLevel('strand'); return
    }
    if (_selLevel === 'domain') {
      _selectDomainV2(hitEntry, hitStrandId, backboneEntries, coneEntries)
      _emitDrillLevel('domain'); return
    }
    if (_selLevel === 'end') {
      _selectBeadV2(hitEntry, hitStrandId, backboneEntries, coneEntries)
      _emitDrillLevel('end'); return
    }
    if (_selLevel === 'xover') {
      // A plain bead carries no crossover — soft-fall to strand for feedback.
      _selectStrandV2(hitStrandId, hitEntry, backboneEntries, coneEntries)
      _emitDrillLevel('xover'); return
    }
    // default: strand-first, then the leaf under the cursor. A repeat click on the
    // already-selected leaf KEEPS it selected (no toggle-clear) — user feedback 2026-06-06.
    const onSameStrand = (_mode === 'strand' || _mode === 'bead') && _strandId === hitStrandId
    if (!onSameStrand) {
      _selectStrandV2(hitStrandId, hitEntry, backboneEntries, coneEntries)
    } else {
      const rep = designRenderer.columnRepAt?.(hitEntry.nuc.helix_id, hitEntry.nuc.bp_index)
      if (rep === 'cylinders' || rep === 'surface') {
        _selectDomainV2(hitEntry, hitStrandId, backboneEntries, coneEntries)   // rep caveat: no bead
      } else {
        _selectBeadV2(hitEntry, hitStrandId, backboneEntries, coneEntries)
      }
    }
    _emitDrillLevel('default')
  }

  // Drill-v2 cone-hit dispatch — mirror of _v2HandleBead for crossover cones.
  function _v2HandleCone(hitCone, hitStrandId, backboneEntries, coneEntries) {
    _clearHoverPreview()
    if (_selLevel === 'cluster') {
      const repNuc = hitCone.fromNuc ?? hitCone.toNuc
      if (!(repNuc && _selectClusterV2(repNuc, hitStrandId, backboneEntries))) {
        _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
      }
      _emitDrillLevel('cluster'); return
    }
    if (_selLevel === 'xover') {
      _selectConeV2(hitCone, hitStrandId, backboneEntries, coneEntries)
      _emitDrillLevel('xover'); return
    }
    if (_selLevel === 'strand' || _selLevel === 'domain' || _selLevel === 'end') {
      // strand level → the whole strand; domain/end have no leaf on a cone → strand.
      _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
      _emitDrillLevel(_selLevel); return
    }
    // default: strand-first, then the cone (xover) under the cursor.
    const onSameStrand = (_mode === 'strand' || _mode === 'cone') && _strandId === hitStrandId
    if (!onSameStrand) _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
    else               _selectConeV2(hitCone, hitStrandId, backboneEntries, coneEntries)
    _emitDrillLevel('default')
  }

  // Select the crossover object behind a hovered/clicked arc (green selection glow).
  // The thin inter-helix arc carries the crossover_id; a 2nd click on the same
  // crossover toggles it off. Returns false (caller falls back to strand) when the
  // arc has no resolvable crossover/forced-ligation.
  function _selectCrossoverV2(arcHit) {
    if (!arcHit.crossover_id) return false
    const design = store.getState().currentDesign
    const xo = design?.crossovers?.find(x => x.id === arcHit.crossover_id)
    const fl = xo ? null : design?.forced_ligations?.find(f => f.id === arcHit.crossover_id)
    const target = xo ?? fl
    if (!target) return false
    if (_mode === 'crossover' && _crossoverId === target.id) { _clearAll(); return true }  // toggle off
    _restoreStrand()
    _mode = 'crossover'; _crossoverId = target.id; _strandId = arcHit.strandId
    // Green glow TUBE along the arc — unified with the red preview tube (user
    // feedback 2026-06-06), replacing the old endpoint-sphere glow.
    designRenderer.setSelectionArc(arcHit.getPositions?.() ?? [])
    store.setState({
      selectedObject: { type: xo ? 'crossover' : 'forced_ligation', id: target.id, data: target },
    })
    return true
  }

  // Drill-v2 crossover-arc dispatch — mirror of _v2HandleCone for the thin inter-helix
  // arc (its cone is hidden, so the arc IS the only pickable crossover target).
  function _v2HandleArc(arcHit, backboneEntries, coneEntries) {
    const hitStrandId = arcHit.strandId
    _clearHoverPreview()
    if (_selLevel === 'cluster') {
      const repNuc = arcHit.fromNuc ?? arcHit.toNuc
      if (!(repNuc && _selectClusterV2(repNuc, hitStrandId, backboneEntries))) {
        _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
      }
      _emitDrillLevel('cluster'); return
    }
    if (_selLevel === 'xover') {
      if (!_selectCrossoverV2(arcHit)) _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
      _emitDrillLevel('xover'); return
    }
    if (_selLevel === 'strand' || _selLevel === 'domain' || _selLevel === 'end') {
      // strand level → the whole strand; domain/end have no leaf on an arc → strand.
      _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
      _emitDrillLevel(_selLevel); return
    }
    // default: strand-first, then the crossover under the cursor.
    const onSameStrand = (_mode === 'strand' || _mode === 'cone' || _mode === 'crossover') && _strandId === hitStrandId
    if (!onSameStrand) {
      _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
    } else if (!_selectCrossoverV2(arcHit)) {
      _selectStrandV2(hitStrandId, null, backboneEntries, coneEntries)
    }
    _emitDrillLevel('default')
  }

  // ── Drill-v2 hover preview ─────────────────────────────────────────────────
  // Lightweight raycast (default level + a selected strand only) that paints a RED
  // glow on the bead/cone under the cursor — the leaf a 2nd click would select —
  // distinct from the GREEN selection glow. Clicking it makes the selection (green).

  function _clearHoverPreview() {
    if (_hoverBead || _hoverCone || _hoverArc) {
      _hoverBead = null
      _hoverCone = null
      _hoverArc  = null
      designRenderer.clearPreviewGlow()
      designRenderer.clearPreviewArc?.()
    }
  }

  // Nearest crossover-arc of the SELECTED strand within _arcHitPx of (sx, sy)
  // (canvas-relative). Reuses the already-computed _strandArcEntries so a pointermove
  // doesn't project every arc in the design — only the selected strand's. Arc lines
  // are pick-by-proximity (thin), not raycast.
  function _findStrandArcAt(sx, sy) {
    let best = null, bestDist = _arcHitPx
    for (const e of _strandArcEntries) {
      const pts = e.getPositions?.() ?? [e.getMidWorld?.()]
      for (const pt of pts) {
        if (!pt) continue
        const sp = _toScreen(pt)
        const d  = Math.hypot(sp.x - sx, sp.y - sy)
        if (d < bestDist) { bestDist = d; best = e }
      }
    }
    return best
  }

  function _pickNearestBeadCone(clientX, clientY) {
    _setNdc(clientX, clientY)
    raycaster.setFromCamera(_ndc, _cam())
    const backboneEntries = designRenderer.getBackboneEntries()
    const coneEntries     = designRenderer.getConeEntries()
    const beadMeshes = [...new Set(backboneEntries.map(e => e.instMesh))].filter(m => m.visible)
    const coneMeshes = [...new Set(coneEntries.map(e => e.instMesh))].filter(m => m.visible)
    const bHits = beadMeshes.length ? raycaster.intersectObjects(beadMeshes) : []
    const cHits = coneMeshes.length ? raycaster.intersectObjects(coneMeshes) : []
    const b0 = bHits[0], c0 = cHits[0]
    const bd = b0?.distance ?? Infinity, cd = c0?.distance ?? Infinity
    if (bd === Infinity && cd === Infinity) return null
    if (cd < bd) {
      const cone = coneEntries.find(e => e.instMesh === c0.object && e.id === c0.instanceId)
      return cone ? { kind: 'cone', cone } : null
    }
    const entry = backboneEntries.find(e => e.instMesh === b0.object && e.id === b0.instanceId)
    return entry ? { kind: 'bead', entry } : null
  }

  function _updateHoverPreview(clientX, clientY) {
    if (!_drillV2 || _selLevel !== 'default' || _mode !== 'strand') { _clearHoverPreview(); return }
    if (clientX > window.innerWidth - 300) { _clearHoverPreview(); return }
    const opts = { drillV2: _drillV2, selLevel: _selLevel, mode: _mode, strandId: _strandId }
    const hit = _pickNearestBeadCone(clientX, clientY)
    let target = hoverPreviewTarget({ ...opts, hit })
    if (!target) {
      // No bead/cone leaf — the thin crossover arc is the only target there (its
      // cone is hidden). Pick it by proximity (18px) among the selected strand's arcs.
      const rect = canvas.getBoundingClientRect()
      const arc = _findStrandArcAt(clientX - rect.left, clientY - rect.top)
      if (arc) target = hoverPreviewTarget({ ...opts, hit: { kind: 'arc', arc } })
    }
    if (!target) { _clearHoverPreview(); return }
    if (target.kind === 'bead') {
      if (_hoverBead === target.entry) return
      _hoverBead = target.entry; _hoverCone = null; _hoverArc = null
      designRenderer.clearPreviewArc?.()
      designRenderer.setPreviewGlow([{ pos: target.entry.pos }])
    } else if (target.kind === 'cone') {
      if (_hoverCone === target.cone) return
      _hoverCone = target.cone; _hoverBead = null; _hoverArc = null
      designRenderer.clearPreviewArc?.()
      designRenderer.setPreviewGlow([{ pos: target.cone.midPos }])
    } else {
      // Crossover arc → a red glow TUBE traced along the arc's polyline.
      if (_hoverArc === target.arc) return
      _hoverArc = target.arc; _hoverBead = null; _hoverCone = null
      designRenderer.clearPreviewGlow()
      designRenderer.setPreviewArc(target.arc.getPositions?.() ?? [])
    }
  }

  // Unified backbone-bead-level hit handler — used by a real bead hit AND by the
  // region overlays (atom / surface / cylinder, via a representative entry). Honours
  // the SAME rules: auto-drill (with the Tab drill-lock) when in auto mode, else the
  // manual selectableTypes granularity. The auto-drill cap is rep-aware (cylinders →
  // domain, surface → strand) via columnRepAt inside _autoDrillBead.
  function _handleBeadHit(hitEntry, backboneEntries, coneEntries, prevOverhangId = null) {
    const hitStrandId = hitEntry.nuc.strand_id
    if (_drillV2) { _v2HandleBead(hitEntry, backboneEntries, coneEntries); return }
    if (_autoDrill()) { _autoDrillBead(hitEntry, hitStrandId, backboneEntries, coneEntries); return }

    const { selectableTypes } = store.getState()
    // Overhang filter → overhang granularity.
    if (selectableTypes.overhangs && hitEntry.nuc.overhang_id) {
      const ovhgId = hitEntry.nuc.overhang_id
      if (prevOverhangId !== ovhgId) {
        _applyMultiOverhangHighlight([ovhgId])
        store.setState({ multiSelectedOverhangIds: [ovhgId] })
      }
      return
    }
    // Domain filter → domain granularity.
    if (selectableTypes.domains) {
      const domainIdx = hitEntry.nuc.domain_index ?? 0
      if (_mode === 'domain' && _strandId === hitStrandId && _domainIndex === domainIdx) {
        _clearAll()
      } else {
        _restoreStrand()
        _mode = 'domain'; _strandId = hitStrandId
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        _highlightDomain(domainIdx)
        const design = store.getState().currentDesign
        const domainObj = design?.strands?.find(s => s.id === hitStrandId)?.domains?.[domainIdx]
        store.setState({
          selectedObject: {
            type: 'domain',
            id:   `${hitStrandId}:${domainIdx}`,
            data: {
              strand_id:    hitStrandId,
              domain_index: domainIdx,
              helix_id:     domainObj?.helix_id    ?? hitEntry.nuc.helix_id,
              direction:    domainObj?.direction   ?? hitEntry.nuc.direction,
              overhang_id:  domainObj?.overhang_id ?? null,
            },
          },
        })
      }
      return
    }
    // Default manual: strand, then nucleotide on repeat clicks.
    if (_mode === 'none' || hitStrandId !== _strandId) {
      _mode = 'strand'; _strandId = hitStrandId; _coneEntry = null
      _highlightStrand(backboneEntries, coneEntries, hitStrandId)
      store.setState({
        selectedObject: _strandSelection(
          hitStrandId ?? `unassigned:${hitEntry.nuc.helix_id}:${hitEntry.nuc.direction}`,
          { helix_id: hitEntry.nuc.helix_id },
        ),
      })
    } else if (_mode === 'strand') {
      _mode = 'bead'; _highlightBead(hitEntry)
      store.setState({ selectedObject: { type: 'nucleotide', id: `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`, data: hitEntry.nuc } })
    } else if (_mode === 'bead' && _beadEntry &&
               _beadEntry.nuc.helix_id  === hitEntry.nuc.helix_id &&
               _beadEntry.nuc.bp_index  === hitEntry.nuc.bp_index &&
               _beadEntry.nuc.direction === hitEntry.nuc.direction) {
      _clearAll()
    } else {
      _mode = 'bead'; _highlightBead(hitEntry)
      store.setState({ selectedObject: { type: 'nucleotide', id: `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`, data: hitEntry.nuc } })
    }
  }

  // Find a representative backbone entry for a strand (optionally constrained to a
  // domain and/or a column rep) — used to route overlay/cylinder hits through the
  // same bead handler. Returns null when the strand renders without beads (e.g. a
  // flexible-segment or ss-linker-bridge run drawn as an arc).
  function _repEntryFor(backboneEntries, strandId, { domainIndex = null, rep = null } = {}) {
    return backboneEntries.find(e =>
      e.nuc.strand_id === strandId &&
      (domainIndex == null || e.nuc.domain_index === domainIndex) &&
      (rep == null || designRenderer.columnRepAt?.(e.nuc.helix_id, e.nuc.bp_index) === rep)) ?? null
  }

  // ── Highlight helpers ────────────────────────────────────────────────────

  function _strandSelection(strandId, extra = {}) {
    // Each ds linker half is a distinct strand for selection purposes — only
    // the clicked one is selected/highlighted. Color/right-click ops still
    // operate on the whole linker via `linkerComponentIds()` inside
    // `_showColorMenu`.
    return {
      type: 'strand',
      id: strandId,
      data: { strand_id: strandId, strand_ids: [strandId], ...extra },
    }
  }

  function _restoreStrand() {
    _clearCylinderSelection()
    for (const e of _strandEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setBeadScale(e, 1.0)
    }
    for (const e of _strandConeEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setConeXZScale(e, e.coneRadius)
    }
    for (const e of _strandArcEntries) {
      e.setColor(e.defaultColor)
    }
    if (_xoverHighlightId) {
      designRenderer.setXoverBeadScale([_xoverHighlightId], 1.0)
      _xoverHighlightId = null
    }
    getOverhangLinkArcs?.()?.setHighlightedStrands?.([])
    _clearSelectionGlow()
    _strandEntries     = []
    _strandConeEntries = []
    _strandArcEntries  = []
    _domainIndex       = null
    _beadEntry         = null
    _coneEntry         = null
    // Hover-preview bead/cone/arc live on the selected strand; drop the pointers and
    // remove the red preview glow (a separate layer the scale-reset above misses).
    _hoverBead = null
    _hoverCone = null
    _hoverArc  = null
    designRenderer.clearPreviewGlow?.()
    designRenderer.clearPreviewArc?.()
    designRenderer.clearSelectionArc?.()   // green crossover-selection tube
  }

  function _highlightStrand(backboneEntries, coneEntries, strandId) {
    _restoreStrand()
    // ds linker halves are independent strands for selection — only the
    // clicked strand id contributes beads/cones/arcs.
    const memberIds    = [strandId]
    const _memberIds   = new Set(memberIds)
    _strandEntries     = backboneEntries.filter(e => _memberIds.has(e.nuc.strand_id))
    _strandConeEntries = coneEntries.filter(e => _memberIds.has(e.strandId))
    _strandArcEntries  = (getUnfoldView?.()?.getArcEntries() ?? []).filter(e => _memberIds.has(e.strandId))
    for (const e of _strandEntries) {
      designRenderer.setBeadScale(e, 1.3)   // scale up; color unchanged
    }
    for (const e of _strandArcEntries) {
      e.setColor(C_FIVE_PRIME)     // green tint for unfold arcs (no glow layer there)
    }
    // Extra-base crossover beads for this strand
    _xoverHighlightId = strandId
    const _xoverGlow = designRenderer.getXoverBeadGlowEntries(memberIds)
    if (_xoverGlow.length > 0) designRenderer.setXoverBeadScale(memberIds, 1.3)
    getOverhangLinkArcs?.()?.setHighlightedStrands?.(memberIds)
    _setSelectionGlow([..._strandEntries, ..._xoverGlow])
    // 5′/3′ end markers — red for 5′ start, blue for 3′ end (all strands)
    for (const e of _strandEntries) {
      if (e.nuc.is_five_prime)  { designRenderer.setEntryColor(e, C_FIVE_PRIME);  designRenderer.setBeadScale(e, 2.0) }
      if (e.nuc.is_three_prime) { designRenderer.setEntryColor(e, C_THREE_PRIME); designRenderer.setBeadScale(e, 2.0) }
    }
  }

  function _highlightDomain(domainIdx) {
    for (const e of _strandEntries) {
      designRenderer.setBeadScale(e, e.nuc.domain_index === domainIdx ? 1.5 : 0.9)
    }
    _domainIndex = domainIdx
    _setSelectionGlow(_strandEntries.filter(e => e.nuc.domain_index === domainIdx))
  }

  function _highlightBead(entry) {
    const otherScale = store.getState().cadnanoActive ? 1.0 : 1.2
    for (const e of _strandEntries) {
      designRenderer.setBeadScale(e, e === entry ? 1.6 : otherScale)
    }
    _beadEntry = entry
    _setSelectionGlow([entry])
  }

  function _highlightCone(entry) {
    for (const e of _strandConeEntries) {
      designRenderer.setConeXZScale(e, e === entry ? 0.12 : e.coneRadius)
      designRenderer.setEntryColor(e, e === entry ? C_SELECT_CONE : C_SELECT_STRAND)
    }
    _coneEntry = entry
  }

  function _clearCylinderSelection() {
    if (_cylStrandId) {
      designRenderer.clearCylinderHighlight()
      _cylStrandId = null
    }
  }

  function _clearAll() {
    _restoreStrand()
    _clearCylinderSelection()
    _mode        = 'none'
    _strandId    = null
    _crossoverId = null
    _resetDrill()
    _emitDrillLevel(null)
    store.setState({ selectedObject: null })
    _clearMultiLoopSkips()
    _clearMultiDomainSelection()
    _clearMultiCrossoverArcs()
    _clearMultiOverhangSelection()
  }

  // ── Multi-selection (Ctrl+drag rectangle lasso) ──────────────────────────

  let _inLassoMode     = false
  let _lassoStart      = null   // { x, y } in client coords
  let _lassoOverlay    = null   // <div> rubber-band rect
  let _multiStrandIds  = []
  let _multiEntries    = []
  let _multiConeEntries = []

  // Multi-selected loop/skip markers.
  // Each entry from getLoopSkipHighlight().getEntries(): { type, helixId, bpIndex, getPosition, setHighlight }.
  let _multiLoopSkipEntries = []

  function _createLassoOverlay() {
    const div = document.createElement('div')
    div.style.cssText = 'position:fixed;border:1.5px dashed #74b9ff;background:rgba(116,185,255,0.07);' +
                        'pointer-events:none;z-index:1000;box-sizing:border-box'
    document.body.appendChild(div)
    return div
  }

  function _updateLassoOverlay(x1, y1, x2, y2) {
    if (!_lassoOverlay) return
    _lassoOverlay.style.left   = Math.min(x1, x2) + 'px'
    _lassoOverlay.style.top    = Math.min(y1, y2) + 'px'
    _lassoOverlay.style.width  = Math.abs(x2 - x1) + 'px'
    _lassoOverlay.style.height = Math.abs(y2 - y1) + 'px'
  }

  function _applyMultiHighlight(strandIds) {
    strandIds = [...new Set((strandIds ?? []).filter(Boolean))]
    // Restore previous multi-highlight without touching store
    for (const e of _multiEntries)     { designRenderer.setEntryColor(e, e.defaultColor); designRenderer.setBeadScale(e, 1.0) }
    for (const e of _multiConeEntries) { designRenderer.setEntryColor(e, e.defaultColor) }
    if (_multiStrandIds.length > 0) designRenderer.setXoverBeadScale(_multiStrandIds, 1.0)
    getOverhangLinkArcs?.()?.setHighlightedStrands?.([])
    designRenderer.clearCylinderHighlight()
    _multiEntries     = designRenderer.getBackboneEntries().filter(e => strandIds.includes(e.nuc.strand_id))
    _multiConeEntries = designRenderer.getConeEntries().filter(e => strandIds.includes(e.strandId))
    _multiStrandIds   = strandIds
    for (const e of _multiEntries) {
      designRenderer.setBeadScale(e, 1.3)
      // 5′/3′ end markers — same treatment as single-strand highlight
      if (e.nuc.is_five_prime)  { designRenderer.setEntryColor(e, C_FIVE_PRIME);  designRenderer.setBeadScale(e, 2.0) }
      if (e.nuc.is_three_prime) { designRenderer.setEntryColor(e, C_THREE_PRIME); designRenderer.setBeadScale(e, 2.0) }
    }
    // Extra-base crossover beads for the selected strands
    const _xoverGlow = designRenderer.getXoverBeadGlowEntries(strandIds)
    if (_xoverGlow.length > 0) designRenderer.setXoverBeadScale(strandIds, 1.3)
    getOverhangLinkArcs?.()?.setHighlightedStrands?.(strandIds)
    // Radioactive glow — unified with single-strand selection glow
    _setSelectionGlow([..._multiEntries, ..._xoverGlow])
    // In cylinder LOD, highlight the selected cylinders.
    if (designRenderer.getCylinderMesh()?.visible) {
      designRenderer.highlightCylinderStrands(strandIds)
    }
  }

  function _clearMultiSelection() {
    for (const e of _multiEntries)     { designRenderer.setEntryColor(e, e.defaultColor); designRenderer.setBeadScale(e, 1.0) }
    for (const e of _multiConeEntries) { designRenderer.setEntryColor(e, e.defaultColor) }
    if (_multiStrandIds.length > 0) designRenderer.setXoverBeadScale(_multiStrandIds, 1.0)
    getOverhangLinkArcs?.()?.setHighlightedStrands?.([])
    designRenderer.clearCylinderHighlight()
    _clearSelectionGlow()
    _multiEntries      = []
    _multiConeEntries  = []
    _multiStrandIds    = []
    store.setState({ multiSelectedStrandIds: [] })
    _clearMultiLoopSkips()
  }

  function _clearMultiLoopSkips() {
    for (const e of _multiLoopSkipEntries) e.setHighlight(false)
    _multiLoopSkipEntries = []
  }

  // ── Multi-domain selection ──────────────────────────────────────────────

  let _multiDomainIds     = []   // Array<{ strandId, domainIndex }>
  let _multiDomainEntries = []   // backbone entries for highlighted domain beads

  function _applyMultiDomainHighlight(domains) {
    // Restore previous domain highlight first.
    for (const e of _multiDomainEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setBeadScale(e, 1.0)
    }
    const keySet = new Set(domains.map(d => `${d.strandId}:${d.domainIndex}`))
    _multiDomainEntries = designRenderer.getBackboneEntries().filter(e =>
      keySet.has(`${e.nuc.strand_id}:${e.nuc.domain_index}`),
    )
    _multiDomainIds = [...domains]
    for (const e of _multiDomainEntries) {
      designRenderer.setEntryColor(e, C_SELECT_STRAND)
      designRenderer.setBeadScale(e, 1.3)
    }
    _setSelectionGlow(_multiDomainEntries)
  }

  function _clearMultiDomainSelection() {
    for (const e of _multiDomainEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setBeadScale(e, 1.0)
    }
    _clearSelectionGlow()
    _multiDomainEntries = []
    _multiDomainIds     = []
    store.setState({ multiSelectedDomainIds: [] })
  }

  // ── Multi-overhang selection ────────────────────────────────────────────

  let _multiOverhangIds     = []   // Array<string> — overhang_id strings
  let _multiOverhangEntries = []   // backbone entries for highlighted overhang beads

  function _applyMultiOverhangHighlight(ovhgIds) {
    for (const e of _multiOverhangEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setBeadScale(e, 1.0)
    }
    const idSet = new Set(ovhgIds)
    _multiOverhangEntries = designRenderer.getBackboneEntries().filter(e => idSet.has(e.nuc.overhang_id))
    _multiOverhangIds = [...ovhgIds]
    for (const e of _multiOverhangEntries) {
      designRenderer.setEntryColor(e, C_SELECT_STRAND)
      designRenderer.setBeadScale(e, 1.3)
    }
    _setSelectionGlow(_multiOverhangEntries)
  }

  function _clearMultiOverhangSelection() {
    for (const e of _multiOverhangEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setBeadScale(e, 1.0)
    }
    _clearSelectionGlow()
    _multiOverhangEntries = []
    _multiOverhangIds     = []
    store.setState({ multiSelectedOverhangIds: [] })
  }

  // ── Multi-domain right-click menu (representation override) ──────────────

  function _showMultiDomainMenu(x, y, domainRefs, _designRenderer) {
    _dismissMenu()
    const menu = _menuBase(x, y)
    const hdr = document.createElement('div')
    hdr.textContent = `${domainRefs.length} domain${domainRefs.length === 1 ? '' : 's'} selected`
    hdr.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                        'border-bottom:1px solid #3a4a5a;margin-bottom:4px'
    menu.appendChild(hdr)
    _appendRepresentationMenu(menu, { domainRefs })
    document.body.appendChild(menu)
    _menuEl = menu
    _menuOutsideListeners(menu)
  }

  // ── Multi-loop/skip right-click menu ────────────────────────────────────

  function _showMultiLoopSkipMenu(x, y) {
    _dismissMenu()
    const entries = _multiLoopSkipEntries
    const nLoops = entries.filter(e => e.type === 'loop').length
    const nSkips = entries.filter(e => e.type === 'skip').length
    const label  = [nLoops && `${nLoops} loop${nLoops > 1 ? 's' : ''}`, nSkips && `${nSkips} skip${nSkips > 1 ? 's' : ''}`].filter(Boolean).join(' + ')
    const menu = _menuBase(x, y)

    const hdr = document.createElement('div')
    hdr.textContent = `${label} selected`
    hdr.style.cssText = 'padding:3px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                        'border-bottom:1px solid #3a4a5a;margin-bottom:4px'
    menu.appendChild(hdr)

    const delItem = _menuItem(`Remove ${label}`, async () => {
      const toRemove = [...entries]
      _clearMultiLoopSkips()
      for (const e of toRemove) {
        await api.insertLoopSkip(e.helixId, e.bpIndex, 0)
      }
    })
    delItem.style.color = '#ff6b6b'
    menu.appendChild(delItem)

    document.body.appendChild(menu)
    _menuEl = menu
    _menuOutsideListeners(menu)
  }

  // ── Ctrl+click nucleotide selection ─────────────────────────────────────

  const C_CTRL_BEAD = 0x00e5ff   // cyan — distinct from selection white and fc orange

  let _ctrlBeads             = []   // [{entry, nuc}, ...] individually ctrl-picked beads
  let _ctrlBeadsChangeCbs    = []   // array — multiple subscribers allowed
  let _selectionGlowEntries = []   // current glow from regular strand/bead selection

  // Merged glow: always combines selection glow + ctrl bead glow.
  function _setSelectionGlow(entries) {
    _selectionGlowEntries = entries
    // Split highlighted entries: bead-rendered domains keep the sphere glow;
    // cylinder-rendered domains get the additive cylinder glow instead (no double
    // halo). Both come from the same entry list, so every highlight path is covered.
    const beadEntries = []
    const cylRefs = new Map()
    for (const e of entries) {
      const sid = e.nuc?.strand_id, di = e.nuc?.domain_index
      if (sid != null && di != null && designRenderer.isDomainCylinder?.(sid, di)) {
        cylRefs.set(`${sid}:${di}`, { strandId: sid, domainIndex: di })
      } else {
        beadEntries.push(e)
      }
    }
    designRenderer.setGlowEntries([...beadEntries, ..._ctrlBeads.map(b => b.entry)])
    designRenderer.glowCylinderDomains([...cylRefs.values()])
  }

  function _clearSelectionGlow() {
    _selectionGlowEntries = []
    designRenderer.clearCylinderDomainGlow?.()
    const ctrlEntries = _ctrlBeads.map(b => b.entry)
    if (ctrlEntries.length) designRenderer.setGlowEntries(ctrlEntries)
    else                    designRenderer.clearGlow()
  }

  function _refreshCtrlGlow() {
    designRenderer.setGlowEntries([..._selectionGlowEntries, ..._ctrlBeads.map(b => b.entry)])
  }

  function _notifyCtrlBeadsChange() {
    const snapshot = [..._ctrlBeads]
    for (const cb of _ctrlBeadsChangeCbs) cb(snapshot)
  }

  function _clearCtrlBeads() {
    for (const b of _ctrlBeads) {
      designRenderer.setEntryColor(b.entry, b.entry.defaultColor)
      designRenderer.setBeadScale(b.entry, 1.0)
      if (b.entry.instMesh.instanceColor)  b.entry.instMesh.instanceColor.needsUpdate  = true
      if (b.entry.instMesh.instanceMatrix) b.entry.instMesh.instanceMatrix.needsUpdate = true
    }
    _ctrlBeads = []
    _refreshCtrlGlow()
    _notifyCtrlBeadsChange()
  }

  // ── Multi-crossover arc selection (Ctrl+click / lasso) ──────────────────
  // Each entry is an arc wrapper from getUnfoldView().getArcEntries().

  const C_MULTI_XOVER_ARC = 0x00e5ff   // cyan — matches ctrl-bead color

  let _multiCrossoverArcs = []   // arc wrapper objects currently multi-selected

  function _applyMultiCrossoverHighlight(arcs) {
    // Restore any previous multi-xover highlight.
    for (const a of _multiCrossoverArcs) a.setColor(a.defaultColor)
    _multiCrossoverArcs = arcs
    for (const a of _multiCrossoverArcs) a.setColor(C_MULTI_XOVER_ARC)
    getUnfoldView?.()?.updateArcGlow(_multiCrossoverArcs)
  }

  function _clearMultiCrossoverArcs() {
    for (const a of _multiCrossoverArcs) a.setColor(a.defaultColor)
    _multiCrossoverArcs = []
    getUnfoldView?.()?.updateArcGlow([])
  }

  function _handleCtrlClickNuc(e) {
    if (e.clientX > window.innerWidth - 300) return

    // Overhang multi-selection: when the overhang filter is on, ctrl+click
    // toggles a hit overhang in/out of _multiOverhangIds (capped at 2 — older
    // ids drop off so the manager popup always sees the most recent two).
    const sel = store.getState().selectableTypes
    if (sel.overhangs) {
      _setNdc(e.clientX, e.clientY)
      raycaster.setFromCamera(_ndc, _cam())
      const backboneEntries = designRenderer.getBackboneEntries()
      const beadMeshes = [...new Set(backboneEntries.map(be => be.instMesh))]
      const hits = raycaster.intersectObjects(beadMeshes)
      if (hits.length) {
        const entry = backboneEntries.find(be =>
          be.instMesh === hits[0].object && be.id === hits[0].instanceId
        )
        const ovhgId = entry?.nuc?.overhang_id
        if (ovhgId) {
          const next = _multiOverhangIds.includes(ovhgId)
            ? _multiOverhangIds.filter(id => id !== ovhgId)
            : [..._multiOverhangIds, ovhgId].slice(-2)   // cap at 2; oldest drops
          _applyMultiOverhangHighlight(next)
          store.setState({ multiSelectedOverhangIds: next })
          return
        }
      }
      // Fall through to ctrl-bead distance picker if click missed any overhang.
    }

    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, _cam())

    const backboneEntries = designRenderer.getBackboneEntries()
    if (!backboneEntries.length) return

    const beadMeshes = [...new Set(backboneEntries.map(be => be.instMesh))]
    const hits = raycaster.intersectObjects(beadMeshes)

    if (!hits.length) {
      _clearCtrlBeads()
      return
    }

    const hit = hits[0]
    const entry = backboneEntries.find(be => be.instMesh === hit.object && be.id === hit.instanceId)
    if (!entry) { _clearCtrlBeads(); return }

    const idx = _ctrlBeads.findIndex(b =>
      b.nuc.helix_id  === entry.nuc.helix_id &&
      b.nuc.bp_index  === entry.nuc.bp_index &&
      b.nuc.direction === entry.nuc.direction
    )
    if (idx >= 0) {
      // Deselect
      designRenderer.setEntryColor(_ctrlBeads[idx].entry, _ctrlBeads[idx].entry.defaultColor)
      designRenderer.setBeadScale(_ctrlBeads[idx].entry, 1.0)
      if (_ctrlBeads[idx].entry.instMesh.instanceColor)  _ctrlBeads[idx].entry.instMesh.instanceColor.needsUpdate  = true
      if (_ctrlBeads[idx].entry.instMesh.instanceMatrix) _ctrlBeads[idx].entry.instMesh.instanceMatrix.needsUpdate = true
      _ctrlBeads.splice(idx, 1)
    } else {
      // Select
      designRenderer.setEntryColor(entry, C_CTRL_BEAD)
      designRenderer.setBeadScale(entry, 1.6)
      if (entry.instMesh.instanceColor)  entry.instMesh.instanceColor.needsUpdate  = true
      if (entry.instMesh.instanceMatrix) entry.instMesh.instanceMatrix.needsUpdate = true
      _ctrlBeads.push({ entry, nuc: entry.nuc })
    }
    _refreshCtrlGlow()
    _notifyCtrlBeadsChange()
  }

  /**
   * Ctrl+left-click: if the crossoverArcs filter is active, try arc proximity
   * first — toggles the arc in/out of the multi-crossover selection.
   * Otherwise falls through to backbone bead selection.
   */
  // Alt+left-click (no drag) → measurement-bead pick.
  // (Was Ctrl-click before the 2026-05-17 modifier remap.)
  function _handleAltClick(e) {
    _handleCtrlClickNuc(e)
  }

  // Shift+left-click (no drag) → additive selection:
  //   - over a crossover arc:  toggle that arc in the multi-crossover-arc set
  //   - over a strand bead:    toggle that strand in the multi-strand set
  // (Was Ctrl-click before the 2026-05-17 modifier remap.)
  function _handleShiftClick(e) {
    const st = store.getState().selectableTypes
    if (st.crossoverArcs) {
      const rect = canvas.getBoundingClientRect()
      const arcHit = _findArcAt(e.clientX - rect.left, e.clientY - rect.top)
      if (arcHit?.crossover_id) {
        const idx = _multiCrossoverArcs.findIndex(a => a.crossover_id === arcHit.crossover_id)
        if (idx >= 0) {
          _multiCrossoverArcs[idx].setColor(_multiCrossoverArcs[idx].defaultColor)
          _multiCrossoverArcs.splice(idx, 1)
        } else {
          arcHit.setColor(C_MULTI_XOVER_ARC)
          _multiCrossoverArcs.push(arcHit)
        }
        getUnfoldView?.()?.updateArcGlow(_multiCrossoverArcs)
        return
      }
    }
    _handleShiftAdditivePick(e)
  }

  // Shift-click additive strand pick. Toggles the hit strand in _multiStrandIds
  // and pushes the updated set to the store. Keeps existing multi-selection
  // intact (the regular non-modifier click is the one that clears it).
  function _handleShiftAdditivePick(e) {
    if (e.clientX > window.innerWidth - 300) return
    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, _cam())
    const backboneEntries = designRenderer.getBackboneEntries()
    const beadMeshes = [...new Set(backboneEntries.map(be => be.instMesh))].filter(m => m.visible)
    if (!beadMeshes.length) return
    const hits = raycaster.intersectObjects(beadMeshes)
    if (!hits.length) return
    const entry = backboneEntries.find(be =>
      be.instMesh === hits[0].object && be.id === hits[0].instanceId
    )
    const strandId = entry?.nuc?.strand_id
    if (!strandId) return
    const present = _multiStrandIds.includes(strandId)
    const next = present
      ? _multiStrandIds.filter(id => id !== strandId)
      : [..._multiStrandIds, strandId]
    if (next.length === 0) _clearMultiSelection()
    else {
      _applyMultiHighlight(next)
      store.setState({ multiSelectedStrandIds: next })
    }
  }

  // Ctrl+click (no drag) in auto-drill mode → additive pick locked to the
  // current drill level. In manual mode (or with no active drill) this is a
  // no-op, preserving the legacy "Ctrl reserved for lasso" behavior.
  function _handleCtrlTypeLockClick(e) {
    if (e.clientX > window.innerWidth - 300) return
    const lvl = _currentDrillType()
    if (lvl === null) return

    if (lvl === 'bead') { _handleCtrlClickNuc(e); return }

    if (lvl === 'xover') {
      const rect = canvas.getBoundingClientRect()
      const arcHit = _findArcAt(e.clientX - rect.left, e.clientY - rect.top)
      if (arcHit?.crossover_id) {
        const idx = _multiCrossoverArcs.findIndex(a => a.crossover_id === arcHit.crossover_id)
        if (idx >= 0) { _multiCrossoverArcs[idx].setColor(_multiCrossoverArcs[idx].defaultColor); _multiCrossoverArcs.splice(idx, 1) }
        else { arcHit.setColor(C_MULTI_XOVER_ARC); _multiCrossoverArcs.push(arcHit) }
        getUnfoldView?.()?.updateArcGlow(_multiCrossoverArcs)
      }
      return
    }

    // strand / domain / cluster all resolve from a backbone bead under the cursor.
    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, _cam())
    const backboneEntries = designRenderer.getBackboneEntries()
    const beadMeshes = [...new Set(backboneEntries.map(b => b.instMesh))].filter(m => m.visible)
    const hits = beadMeshes.length ? raycaster.intersectObjects(beadMeshes) : []
    if (!hits.length) return
    const entry = backboneEntries.find(b => b.instMesh === hits[0].object && b.id === hits[0].instanceId)
    if (!entry?.nuc?.strand_id) return

    if (lvl === 'strand') {
      _handleShiftAdditivePick(e)   // toggles the hit strand in/out of _multiStrandIds
    } else if (lvl === 'domain') {
      const strandId = entry.nuc.strand_id
      const domainIndex = entry.nuc.domain_index ?? 0
      const key = `${strandId}:${domainIndex}`
      const present = _multiDomainIds.some(d => `${d.strandId}:${d.domainIndex}` === key)
      const next = present
        ? _multiDomainIds.filter(d => `${d.strandId}:${d.domainIndex}` !== key)
        : [..._multiDomainIds, { strandId, domainIndex }]
      if (next.length === 0) _clearMultiDomainSelection()
      else { _applyMultiDomainHighlight(next); store.setState({ multiSelectedDomainIds: next }) }
    } else if (lvl === 'cluster') {
      const design = store.getState().currentDesign
      const cid = _resolveClusterId(entry.nuc, design)
      if (!cid) return
      const f = clusterMemberFilter(design.cluster_transforms.find(c => c.id === cid), design)
      if (!f) return
      const ids = [...new Set(backboneEntries.filter(b => f(b.nuc)).map(b => b.nuc.strand_id).filter(Boolean))]
      const allPresent = ids.length > 0 && ids.every(id => _multiStrandIds.includes(id))
      const next = allPresent
        ? _multiStrandIds.filter(id => !ids.includes(id))
        : [...new Set([..._multiStrandIds, ...ids])]
      if (next.length === 0) _clearMultiSelection()
      else { _applyMultiHighlight(next); store.setState({ multiSelectedStrandIds: next }) }
    }
  }

  function _finalizeLasso(endX, endY) {
    _inLassoMode = false
    canvas.style.cursor = ''
    if (_lassoOverlay) { _lassoOverlay.remove(); _lassoOverlay = null }
    if (!_lassoStart) return

    const sx1 = Math.min(_lassoStart.x, endX)
    const sy1 = Math.min(_lassoStart.y, endY)
    const sx2 = Math.max(_lassoStart.x, endX)
    const sy2 = Math.max(_lassoStart.y, endY)
    _lassoStart = null

    if (sx2 - sx1 < 4 && sy2 - sy1 < 4) return   // too small — treat as click-miss

    // Convert lasso rect from client→canvas-relative coords for _toScreen comparison
    const rect = canvas.getBoundingClientRect()
    const cx1 = sx1 - rect.left,  cy1 = sy1 - rect.top
    const cx2 = sx2 - rect.left,  cy2 = sy2 - rect.top

    const mat = new THREE.Matrix4()
    const pos = new THREE.Vector3()
    const strandIdSet   = new Set()
    const domainKeyMap  = new Map()   // 'strandId:domainIndex' → { strandId, domainIndex }
    const ovhangIdSet   = new Set()   // overhang_id strings
    const endEntries    = []   // beads captured into _ctrlBeads (ends, or all at bead drill level)
    const clusterHitNucs = []  // nucs of in-rect beads, when drilling at cluster level

    const st = store.getState().selectableTypes
    // What the lasso captures (single source of truth, unit-tested in
    // selection_level.js). In drill-v2 the engaged `_selLevel` decides — the
    // lasso captures the SAME element a click at that level would (ISSUE-4
    // filter-audit fix for "Tab to ends, lasso grabs a cluster"). In legacy, an
    // active auto-drill type-locks to its level; otherwise selectableTypes gates.
    const cap = lassoCaptureType({
      drillV2:         _drillV2,
      selLevel:        _selLevel,
      drillType:       _currentDrillType(),
      selectableTypes: st,
    })
    const beadLevelLasso = cap.beadLevel
    const useStrands  = cap.strands
    const useDomains  = cap.domains
    const useEnds     = cap.ends
    const useOvhg     = cap.overhangs
    const useLoops    = cap.loops
    const useSkips    = cap.skips
    const useXover    = cap.xover
    const useCluster  = cap.cluster
    const cylMesh = designRenderer.getCylinderMesh()
    // Global LOD level, not mesh .visible — mixed-rep makes cylinders visible at full LOD.
    const inCylinderLOD = (designRenderer.getDetailLevel?.() ?? 0) === 2

    // ── Cylinder LOD strands ───────────────────────────────────────────────
    // When iHelixCylinders is visible, project each cylinder center into screen
    // space and collect strand IDs that fall inside the lasso rect.
    // Bead iteration is skipped — beads are hidden in this mode.
    if (inCylinderLOD && (useStrands || useCluster)) {
      const cylData = designRenderer.getCylinderDomainData()
      const design  = store.getState().currentDesign
      const strandTypeMap = new Map((design?.strands ?? []).map(s => [s.id, s.strand_type]))
      for (const dom of cylData) {
        if (!dom.strandId) continue
        const stype = strandTypeMap.get(dom.strandId)
        if (stype === 'scaffold' && !st.scaffold) continue
        if (stype !== 'scaffold' && !st.staples)  continue
        cylMesh.getMatrixAt(dom.cylIdx, mat)
        pos.setFromMatrixPosition(mat)
        const sp = _toScreen(pos)
        if (sp.x >= cx1 && sp.x <= cx2 && sp.y >= cy1 && sp.y <= cy2) {
          strandIdSet.add(dom.strandId)
        }
      }
    }

    // ── Backbone beads (strands + ends) — skipped in cylinder LOD ──────────
    if (!inCylinderLOD) {
    for (const entry of designRenderer.getBackboneEntries()) {
      if (!entry.nuc.strand_id) continue
      entry.instMesh.getMatrixAt(entry.id, mat)
      pos.setFromMatrixPosition(mat)
      const sp = _toScreen(pos)
      if (sp.x < cx1 || sp.x > cx2 || sp.y < cy1 || sp.y > cy2) continue

      const isScaffold = entry.nuc.strand_type === 'scaffold'
      const isStaple   = entry.nuc.strand_type === 'staple'
      const isEnd      = entry.nuc.is_five_prime || entry.nuc.is_three_prime

      const typeAllowed = isScaffold ? st.scaffold : st.staples

      // Captures individual beads into _ctrlBeads. Manual: ends only. Bead drill
      // level: every bead in the rect.
      if (typeAllowed && useEnds && (beadLevelLasso || isEnd)) {
        endEntries.push(entry)
      }

      // Strands capture whole strands into the multi-select set.
      if (typeAllowed && useStrands) {
        strandIdSet.add(entry.nuc.strand_id)
      }

      // Domains capture per-domain groups.
      if (typeAllowed && useDomains) {
        const k = `${entry.nuc.strand_id}:${entry.nuc.domain_index ?? 0}`
        if (!domainKeyMap.has(k)) {
          domainKeyMap.set(k, { strandId: entry.nuc.strand_id, domainIndex: entry.nuc.domain_index ?? 0 })
        }
      }

      // Cluster drill level: record the in-rect nuc; clusters resolved after the loop.
      if (useCluster) clusterHitNucs.push(entry.nuc)

      // Overhangs capture by overhang_id (independent — no scaffold/staple filter).
      if (useOvhg && entry.nuc.overhang_id) {
        ovhangIdSet.add(entry.nuc.overhang_id)
      }
    }
    }

    // ── Cluster drill level → expand hit beads to their clusters' strands ──────
    if (useCluster && clusterHitNucs.length) {
      const design = store.getState().currentDesign
      const cts = design?.cluster_transforms ?? []
      const cidSet = new Set()
      for (const nuc of clusterHitNucs) {
        const cid = _resolveClusterId(nuc, design)
        if (cid) cidSet.add(cid)
      }
      for (const cid of cidSet) {
        const f = clusterMemberFilter(cts.find(c => c.id === cid), design)
        if (!f) continue
        for (const e of designRenderer.getBackboneEntries()) {
          if (f(e.nuc) && e.nuc.strand_id) strandIdSet.add(e.nuc.strand_id)
        }
      }
    }

    // ── Loop/skip markers ──────────────────────────────────────────────────
    if (useLoops || useSkips) {
      const lsh = getLoopSkipHighlight?.()
      if (lsh) {
        const newLsEntries = []
        for (const e of lsh.getEntries()) {
          if (e.type === 'loop' && !useLoops) continue
          if (e.type === 'skip' && !useSkips) continue
          const sp = _toScreen(e.getPosition())
          if (sp.x >= cx1 && sp.x <= cx2 && sp.y >= cy1 && sp.y <= cy2) {
            newLsEntries.push(e)
          }
        }
        if (newLsEntries.length) {
          _clearMultiLoopSkips()
          _multiLoopSkipEntries = newLsEntries
          for (const e of _multiLoopSkipEntries) e.setHighlight(true)
          return  // loop/skip selection takes precedence over strands if any captured
        }
      }
    }

    // ── Crossover arcs (additive) ─────────────────────────────────────────
    if (useXover) {
      const arcEntries = getUnfoldView?.()?.getArcEntries() ?? []
      const existingIds = new Set(_multiCrossoverArcs.map(a => a.crossover_id))
      const newArcs = []
      for (const arc of arcEntries) {
        if (!arc.crossover_id) continue
        if (existingIds.has(arc.crossover_id)) continue
        const sp = _toScreen(arc.getMidWorld())
        if (sp.x >= cx1 && sp.x <= cx2 && sp.y >= cy1 && sp.y <= cy2) {
          newArcs.push(arc)
        }
      }
      if (newArcs.length) {
        _applyMultiCrossoverHighlight([..._multiCrossoverArcs, ...newArcs])
      }
    }

    // ── Domain multi-select result (additive) ────────────────────────────
    if (domainKeyMap.size) {
      const newDomains    = [...domainKeyMap.values()]
      const existingKeys  = new Set(_multiDomainIds.map(d => `${d.strandId}:${d.domainIndex}`))
      const allDomains    = [..._multiDomainIds]
      for (const d of newDomains) {
        if (!existingKeys.has(`${d.strandId}:${d.domainIndex}`)) allDomains.push(d)
      }
      _applyMultiDomainHighlight(allDomains)
      store.setState({ multiSelectedDomainIds: allDomains })
    }

    // ── Overhang multi-select result (additive) ───────────────────────────
    if (ovhangIdSet.size) {
      const allOvhg = [...new Set([..._multiOverhangIds, ...ovhangIdSet])]
      _applyMultiOverhangHighlight(allOvhg)
      store.setState({ multiSelectedOverhangIds: allOvhg })
    }

    // ── Strand multi-select result (additive) ─────────────────────────────
    const strandIds = [...strandIdSet]
    if (strandIds.length) {
      const allStrands = [...new Set([..._multiStrandIds, ...strandIds])]
      _applyMultiHighlight(allStrands)
      store.setState({ multiSelectedStrandIds: allStrands })
    }

    // ── End bead ctrl-selection (applied after strand highlight so gold wins) ─
    if (endEntries.length) {
      _clearCtrlBeads()
      for (const entry of endEntries) {
        designRenderer.setEntryColor(entry, C_CTRL_BEAD)
        designRenderer.setBeadScale(entry, 1.6)
        if (entry.instMesh.instanceColor)  entry.instMesh.instanceColor.needsUpdate  = true
        if (entry.instMesh.instanceMatrix) entry.instMesh.instanceMatrix.needsUpdate = true
        _ctrlBeads.push({ entry, nuc: entry.nuc })
      }
      _refreshCtrlGlow()
      _notifyCtrlBeadsChange()
    }
  }

  // ── Shared NDC + screen helpers ──────────────────────────────────────────

  function _setNdc(clientX, clientY) {
    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((clientX - rect.left) / rect.width)  *  2 - 1,
      -((clientY - rect.top)  / rect.height) * 2 + 1,
    )
  }

  /** Project a world position to canvas-relative screen coordinates. */
  function _toScreen(worldPos) {
    const v    = worldPos.clone().project(_cam())
    const rect = canvas.getBoundingClientRect()
    return {
      x: (v.x *  0.5 + 0.5) * rect.width,
      y: (v.y * -0.5 + 0.5) * rect.height,
    }
  }

  /**
   * Find the arc entry whose midpoint is closest to (sx, sy) in screen space,
   * within _arcHitPx pixels.  Returns null if nothing is close enough.
   */
  function _findArcAt(sx, sy) {
    const arcEntries = getUnfoldView?.()?.getArcEntries() ?? []
    if (!arcEntries.length) return null
    let best = null, bestDist = _arcHitPx
    for (const e of arcEntries) {
      const pts = e.getPositions?.() ?? [e.getMidWorld()]
      for (const pt of pts) {
        const sp = _toScreen(pt)
        const d  = Math.hypot(sp.x - sx, sp.y - sy)
        if (d < bestDist) { bestDist = d; best = e }
      }
    }
    return best
  }

  // ── Left-click ───────────────────────────────────────────────────────────

  // Capture-phase: disable controls before OrbitControls sees Ctrl/Alt/Shift+left
  // so it cannot start a pan or rotate gesture that competes with our selection
  // click (Ctrl-drag → lasso; Alt-click → bead pick; Shift-click → additive pick).
  canvas.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !controls) return
    if (e.ctrlKey || e.altKey || e.shiftKey) controls.enabled = false
  }, { capture: true })

  let _downPos     = null
  let _ctrlDownPos = null   // pending Ctrl+left-down — Ctrl-drag = lasso; bare click is a no-op now
  let _altDownPos  = null   // pending Alt+left-down — release without drag = measurement bead
  let _shiftDownPos = null  // pending Shift+left-down — release without drag = additive multi-select

  canvas.addEventListener('pointerdown', e => {
    if (e.button !== 0) return
    if (isDisabled?.()) return

    // Modifier precedence: Alt > Shift > Ctrl. They never combine meaningfully
    // here, so the first match wins. Alt-down records position for measurement
    // bead pick; Shift-down for additive multi-select; Ctrl-down for the lasso
    // (drag detected on move).
    if (e.altKey) {
      _altDownPos = { x: e.clientX, y: e.clientY }
      return
    }
    if (e.shiftKey) {
      _shiftDownPos = { x: e.clientX, y: e.clientY }
      return
    }
    if (e.ctrlKey) {
      _ctrlDownPos = { x: e.clientX, y: e.clientY }
      return
    }

    _downPos = { x: e.clientX, y: e.clientY }

    // Disable OrbitControls for this click if a bead, cone, or cylinder is under the cursor,
    // so the camera does not drift when the user selects a strand.
    // Skip when the CG root is hidden (atomistic/surface mode): Three.js r172 does not check
    // visible in Raycaster.intersectObjects, so hidden InstancedMeshes would still register
    // hits and incorrectly disable controls.
    const cgRootVisible = designRenderer.getHelixCtrl()?.root?.visible !== false
    if (controls && cgRootVisible) {
      _setNdc(e.clientX, e.clientY)
      raycaster.setFromCamera(_ndc, _cam())
      // Filter to visible meshes only — Three.js r172+ ignores .visible in
      // intersectObjects, so hidden meshes (e.g. iHelixCylinders in full-detail
      // mode, or iSpheres/iCubes in cylinder-LOD mode) would otherwise register
      // false hits at their stale design-geometry positions after cluster moves.
      const beadMeshes = [...new Set(designRenderer.getBackboneEntries().map(e => e.instMesh))].filter(m => m.visible)
      const coneMeshes = [...new Set(designRenderer.getConeEntries().map(e => e.instMesh))].filter(m => m.visible)
      const cylMesh    = designRenderer.getCylinderMesh()
      const beadHit = beadMeshes.length > 0 && raycaster.intersectObjects(beadMeshes).length > 0
      const coneHit = coneMeshes.length > 0 && raycaster.intersectObjects(coneMeshes).length > 0
      const cylHit  = (cylMesh?.visible) ? raycaster.intersectObjects([cylMesh]).length > 0 : false
      if (beadHit || coneHit || cylHit) controls.enabled = false
    }
  })

  canvas.addEventListener('pointermove', e => {
    // Drill-v2 hover preview (default level + strand selected) — pops the bead/cone
    // under the cursor. Skipped during a ctrl/lasso drag.
    if (_drillV2 && !_ctrlDownPos && !_inLassoMode && !isDisabled?.()) _updateHoverPreview(e.clientX, e.clientY)
    // If ctrl is held and we haven't yet started a lasso, check if the drag threshold is exceeded.
    if (_ctrlDownPos && !_inLassoMode) {
      if (Math.hypot(e.clientX - _ctrlDownPos.x, e.clientY - _ctrlDownPos.y) > 4) {
        _inLassoMode  = true
        _lassoStart   = _ctrlDownPos
        _ctrlDownPos  = null
        _lassoOverlay = _createLassoOverlay()
        _updateLassoOverlay(_lassoStart.x, _lassoStart.y, e.clientX, e.clientY)
        canvas.style.cursor = 'crosshair'
        // Clear single-object state but preserve multi-selection for additive lasso.
        _restoreStrand()
        _clearCylinderSelection()
        _mode     = 'none'
        _strandId = null
        store.setState({ selectedObject: null })
        _clearMultiLoopSkips()
      }
      return
    }
    if (!_inLassoMode || !_lassoStart) return
    _updateLassoOverlay(_lassoStart.x, _lassoStart.y, e.clientX, e.clientY)
  })

  canvas.addEventListener('pointerup', e => {
    if (controls) controls.enabled = true
    if (e.button !== 0) return

    // Lasso finalize
    if (_inLassoMode) {
      _ctrlDownPos = null
      _altDownPos = null
      _shiftDownPos = null
      _finalizeLasso(e.clientX, e.clientY)
      return
    }

    // Alt+left click (no drag) → measurement-bead pick (was Ctrl-click).
    if (_altDownPos) {
      const moved = Math.hypot(e.clientX - _altDownPos.x, e.clientY - _altDownPos.y)
      _altDownPos = null
      if (moved <= 4) _handleAltClick(e)
      return
    }

    // Shift+left click (no drag) → additive multi-select / crossover-arc toggle.
    if (_shiftDownPos) {
      const moved = Math.hypot(e.clientX - _shiftDownPos.x, e.clientY - _shiftDownPos.y)
      _shiftDownPos = null
      if (moved <= 4) _handleShiftClick(e)
      return
    }

    // Ctrl+left click (no drag): in auto-drill mode, additive pick locked to the
    // current drill level (cluster/strand/domain/bead/xover). In manual mode it
    // stays a no-op — Ctrl+drag is the lasso; bead/arc toggles are Alt/Shift.
    if (_ctrlDownPos) {
      const moved = Math.hypot(e.clientX - _ctrlDownPos.x, e.clientY - _ctrlDownPos.y)
      _ctrlDownPos = null
      if (moved <= 4) _handleCtrlTypeLockClick(e)
      return
    }

    if (_downPos && Math.hypot(e.clientX - _downPos.x, e.clientY - _downPos.y) > 4) return
    if (e.clientX > window.innerWidth - 300) return

    _dismissMenu()

    // Save the single-selected overhang ID before clearing it — used below to detect
    // a second click on the same overhang (toggle-off).
    const _prevOverhangId = _multiOverhangIds.length === 1 ? _multiOverhangIds[0] : null

    // Regular left click — clear any active multi-selection
    if (_multiStrandIds.length > 0)   _clearMultiSelection()
    if (_multiDomainIds.length > 0)   _clearMultiDomainSelection()
    if (_multiOverhangIds.length > 0) _clearMultiOverhangSelection()
    if (_multiCrossoverArcs.length > 0) _clearMultiCrossoverArcs()

    // Regular (non-ctrl) click clears the ctrl-click nucleotide selection
    if (_ctrlBeads.length > 0) _clearCtrlBeads()

    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, _cam())

    const { selectableTypes } = store.getState()

    const backboneEntries = designRenderer.getBackboneEntries()
    const coneEntries     = designRenderer.getConeEntries()

    // Respect selection filter
    const selBackbone = backboneEntries.filter(e => {
      if (selectableTypes.overhangs && e.nuc.overhang_id) return true
      const isScaffold = e.nuc.strand_type === 'scaffold'
      const isEnd      = e.nuc.is_five_prime || e.nuc.is_three_prime
      if (!(isScaffold ? selectableTypes.scaffold : selectableTypes.staples)) return false
      if (selectableTypes.ends && isEnd) return true
      return selectableTypes.strands || selectableTypes.domains
    })
    const selCones = coneEntries.filter(e => {
      if (!selectableTypes.strands) return false
      const isScaf = e.fromNuc?.strand_type === 'scaffold'
      return isScaf ? selectableTypes.scaffold : selectableTypes.staples
    })

    // Raycast against the VISIBLE bead/cone InstancedMeshes, then find the closest
    // intersection whose instanceId belongs to a selectable entry. Filtering by
    // actual mesh visibility (rather than a "cylinder LOD" flag) is what makes
    // mixed-representation work: in true cylinder LOD the bead meshes are hidden →
    // filtered out → cylinder-hit fallback below; at full LOD (incl. mixed-rep,
    // where iHelixCylinders is visible too) beads stay selectable.
    const beadMeshes = [...new Set(backboneEntries.map(e => e.instMesh))].filter(m => m.visible)
    const coneMeshes = [...new Set(coneEntries.map(e => e.instMesh))].filter(m => m.visible)

    const allBeadHits = beadMeshes.length ? raycaster.intersectObjects(beadMeshes) : []
    const allConeHits = coneMeshes.length ? raycaster.intersectObjects(coneMeshes) : []

    // A column rendered as surface/vdw/ballstick is drawn by an overlay; its CG
    // beads/cones are alpha-0 but keep full-scale matrices, so exclude them from
    // bead/cone hits — the atom/surface hit below should win there.
    const _isOverlayCol = (nuc) => {
      const r = nuc && designRenderer.columnRepAt?.(nuc.helix_id, nuc.bp_index)
      return r === 'vdw' || r === 'ballstick' || r === 'surface'
    }
    const beadHit0 = allBeadHits.find(h => {
      const e = selBackbone.find(e => e.instMesh === h.object && e.id === h.instanceId)
      return e && !_isOverlayCol(e.nuc)
    })
    const coneHit0 = allConeHits.find(h => {
      const e = selCones.find(e => e.instMesh === h.object && e.id === h.instanceId)
      return e && !_isOverlayCol(e.fromNuc)
    })

    const beadDist = beadHit0?.distance ?? Infinity
    const coneDist = coneHit0?.distance ?? Infinity

    // ── Protein hit ──────────────────────────────────────────────────────────
    // Click-to-select a free-standing or attached protein. Takes precedence
    // only when it is the CLOSEST hit (respects depth vs DNA). The atom's
    // helix_id carries the sentinel "__protein__{attachmentId}".
    const protRenderer = getProteinRenderer?.()
    if (protRenderer) {
      const protHit = protRenderer.raycastPick(raycaster)
      if (protHit && protHit.distance <= Math.min(beadDist, coneDist)) {
        const hid = protHit.atom?.helix_id || ''
        const attachmentId = hid.startsWith('__protein__') ? hid.slice('__protein__'.length) : null
        if (attachmentId) {
          _restoreStrand()
          _clearCylinderSelection()
          _mode = 'none'
          _strandId = null
          store.setState({ selectedObject: { type: 'protein', id: attachmentId, data: { attachment_id: attachmentId } } })
          return
        }
      }
    }

    // ── Region overlay hits (per-region surface / vdw / ballstick) ───────────
    // Atoms are the click target in atomistic regions; the surface mesh in surface
    // regions. Each wins only when it is the closest hit.
    let _atomHit = null
    for (const rr of [getRegionVdwRenderer?.(), getRegionBallstickRenderer?.()]) {
      if (!rr || rr.getMode() === 'off') continue
      const h = rr.raycastPick(raycaster)
      if (h && (!_atomHit || h.distance < _atomHit.distance)) _atomHit = h
    }
    const _surfMesh = getRegionSurfaceRenderer?.()?.getMesh?.()
    const _surfHit  = _surfMesh?.visible ? raycaster.intersectObject(_surfMesh, false)[0] : null
    const _atomDist = _atomHit?.distance ?? Infinity
    const _surfDist = _surfHit?.distance ?? Infinity

    if (_atomHit && _atomDist <= Math.min(beadDist, coneDist, _surfDist)) {
      // Atom hit → route the atom's nucleotide through the unified bead handler
      // (auto-drill / manual / Tab rules). Falls back to strand for atoms with no
      // backbone entry (extra-base / aux, or arc-rendered flexible/ss-linker nucs).
      const a = _atomHit.atom
      const hitEntry = backboneEntries.find(e =>
        e.nuc.helix_id === a.helix_id && e.nuc.bp_index === a.bp_index && e.nuc.direction === a.direction)
      if (hitEntry) { _handleBeadHit(hitEntry, backboneEntries, coneEntries, _prevOverhangId); return }
      if (a.strand_id) {
        _restoreStrand()
        _mode = 'strand'; _strandId = a.strand_id
        _highlightStrand(backboneEntries, coneEntries, a.strand_id)
        store.setState({ selectedObject: _strandSelection(a.strand_id) })
        return
      }
    }

    if (_surfHit && _surfDist <= Math.min(beadDist, coneDist, _atomDist)) {
      // Surface hit → strand (vertices carry nearest-atom strand id). Route a
      // surface-column representative through the bead handler so the auto-drill
      // caps at strand (columnRepAt==='surface') and manual/Tab rules apply.
      const strandId = getRegionSurfaceRenderer().strandIdAt(_surfHit.face)
      if (strandId) {
        const rep = _repEntryFor(backboneEntries, strandId, { rep: 'surface' })
        if (rep) { _handleBeadHit(rep, backboneEntries, coneEntries, _prevOverhangId); return }
        _restoreStrand()   // arc-rendered region (no beads) → strand select
        _mode = 'strand'; _strandId = strandId
        _highlightStrand(backboneEntries, coneEntries, strandId)
        store.setState({ selectedObject: _strandSelection(strandId) })
        return
      }
    }

    // ── Cylinder LOD hit (active in global cylinder LOD, where beads are hidden,
    // so beadDist/coneDist are Infinity). Drives the SAME drill as a bead hit but
    // capped cluster → strand → domain (no bead level for cylinders). ──────────
    if (beadDist === Infinity && coneDist === Infinity && selectableTypes.strands) {
      const cylMesh   = designRenderer.getCylinderMesh()
      const ovhgCyl   = designRenderer.getOverhangCylinderMesh?.()
      const bridgeCyl = designRenderer.getLinkerBridgeCylinderMesh?.()
      const cylTargets = [cylMesh, ovhgCyl, bridgeCyl].filter(m => m?.visible)
      if (cylTargets.length) {
        const cylHit0 = raycaster.intersectObjects(cylTargets)[0]
        if (cylHit0 != null) {
          // ds-linker bridge cylinder → select the BRIDGE domain (route via a bead
          // ON the bridge helix so drill/right-click target the bridge, independent
          // of the linker's binding domains). ss linker (no beads) → strand select.
          if (cylHit0.object === bridgeCyl) {
            const br = designRenderer.getLinkerBridgeCylinderAt(cylHit0.instanceId)
            if (br?.strandId && selectableTypes.staples) {
              const rep = backboneEntries.find(e =>
                e.nuc.strand_id === br.strandId && e.nuc.helix_id === br.bridgeHelixId)
                ?? _repEntryFor(backboneEntries, br.strandId)
              if (rep) { _handleBeadHit(rep, backboneEntries, coneEntries, _prevOverhangId); return }
              _restoreStrand()
              _mode = 'strand'; _strandId = br.strandId
              _highlightStrand(backboneEntries, coneEntries, br.strandId)
              store.setState({ selectedObject: _strandSelection(br.strandId) })
              return
            }
          }
          const dom = cylHit0.object === bridgeCyl ? null
            : cylHit0.object === ovhgCyl
              ? designRenderer.getOverhangCylinderDomainAt(cylHit0.instanceId)
              : designRenderer.getCylinderDomainAt(cylHit0.instanceId)
          if (dom?.strandId) {
            const design = store.getState().currentDesign
            const strand = design?.strands?.find(s => s.id === dom.strandId)
            const isScaffold = strand?.strand_type === 'scaffold'
            if (isScaffold ? selectableTypes.scaffold : selectableTypes.staples) {
              // Route a domain representative through the unified handler — auto-drill
              // caps at domain (columnRepAt==='cylinders'), manual/Tab rules apply.
              const rep = _repEntryFor(backboneEntries, dom.strandId, { domainIndex: dom.domainIndex })
              if (rep) { _handleBeadHit(rep, backboneEntries, coneEntries, _prevOverhangId); return }
            }
          }
        }
      }
    }

    if (beadDist === Infinity && coneDist === Infinity) {
      // No bead or cone hit — if zoom scope has a pre-hovered strand, use it.
      const hoverEntry = getHoverEntry?.()
      if (hoverEntry) {
        const hitStrandId = hoverEntry.nuc.strand_id
        if (_mode === 'none' || hitStrandId !== _strandId) {
          _mode     = 'strand'
          _strandId = hitStrandId
          _highlightStrand(backboneEntries, coneEntries, hitStrandId)
          store.setState({ selectedObject: _strandSelection(hitStrandId) })
        }
        return
      }

      const ssLinkHit = selectableTypes.strands
        ? getOverhangLinkArcs?.()?.hitTest?.(e.clientX, e.clientY, _cam(), canvas)
        : null
      if (ssLinkHit?.strandId) {
        // hitTest returns the strand id of the actually-hit arc — for a ds
        // linker that's `__a` or `__b`, for ss it's `__s`. Selection is
        // per-strand: clicking the same strand again clears.
        const hitStrandId = ssLinkHit.strandId
        if (_mode === 'none' || hitStrandId !== _strandId) {
          _mode     = 'strand'
          _strandId = hitStrandId
          _highlightStrand(backboneEntries, coneEntries, hitStrandId)
          store.setState({ selectedObject: _strandSelection(hitStrandId, { linker_connection_id: ssLinkHit.connId }) })
        } else {
          _clearAll()
        }
        return
      }

      // No bead or cone hit — try arc proximity.
      // Arc lines are rendered exclusively by unfold_view.js — all crossover
      // arcs are found via _findArcAt.  When the crossoverArcs filter is on
      // and the hit arc has a crossover_id, select the crossover object.
      const rect2 = canvas.getBoundingClientRect()
      const arcHit = _findArcAt(e.clientX - rect2.left, e.clientY - rect2.top)
      // Drill-v2: the crossover arc is part of the strand→crossover click ladder
      // (strand-first, then the crossover under the cursor — green selection glow).
      if (_drillV2) {
        if (arcHit) { _v2HandleArc(arcHit, backboneEntries, coneEntries); return }
        _clearAll(); return
      }
      if (!arcHit) { _clearAll(); return }

      // Crossover-object selection (when crossoverArcs filter is active)
      if (selectableTypes.crossoverArcs && arcHit.crossover_id) {
        const design = store.getState().currentDesign
        const xo = design?.crossovers?.find(x => x.id === arcHit.crossover_id)
        const fl = xo ? null : design?.forced_ligations?.find(f => f.id === arcHit.crossover_id)
        const target = xo ?? fl
        if (target) {
          if (_mode === 'crossover' && _crossoverId === target.id) {
            _clearAll(); return   // toggle off
          }
          _restoreStrand()
          _mode = 'crossover'
          _crossoverId = target.id
          _strandId = null
          // Green glow TUBE along the arc (unified with the red preview tube).
          designRenderer.setSelectionArc(arcHit.getPositions?.() ?? [])
          store.setState({
            selectedObject: { type: xo ? 'crossover' : 'forced_ligation', id: target.id, data: target },
          })
          return
        }
      }

      if (!arcHit.strandId) { _clearAll(); return }
      const hitStrandId = arcHit.strandId
      if (_mode === 'none' || hitStrandId !== _strandId) {
        _mode     = 'strand'
        _strandId = hitStrandId
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        store.setState({ selectedObject: _strandSelection(hitStrandId) })
      } else {
        // Second click on same strand arc → select as cone-equivalent
        _mode = 'cone'
        const { fromNuc, toNuc } = arcHit
        store.setState({
          selectedObject: {
            type: 'cone',
            id:   `${fromNuc.helix_id}:${fromNuc.bp_index}:${fromNuc.direction}→${toNuc.helix_id}:${toNuc.bp_index}:${toNuc.direction}`,
            data: { fromNuc, toNuc, strand_id: hitStrandId },
          },
        })
      }
      return
    }

    if (coneDist < beadDist) {
      // ── Cone hit ────────────────────────────────────────────────────────
      const hitCone = selCones.find(e => e.instMesh === coneHit0.object && e.id === coneHit0.instanceId)
      if (!hitCone) return
      const hitStrandId = hitCone.strandId

      if (_drillV2) { _v2HandleCone(hitCone, hitStrandId, backboneEntries, coneEntries); return }
      if (_autoDrill()) { _autoDrillCone(hitCone, hitStrandId, backboneEntries, coneEntries); return }

      if (_mode === 'none' || hitStrandId !== _strandId) {
        _mode     = 'strand'
        _strandId = hitStrandId
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        store.setState({ selectedObject: _strandSelection(hitStrandId) })
      } else {
        // Second click within same strand → select this cone
        _mode = 'cone'
        _highlightCone(hitCone)
        const { fromNuc, toNuc } = hitCone
        store.setState({
          selectedObject: {
            type: 'cone',
            id:   `${fromNuc.helix_id}:${fromNuc.bp_index}:${fromNuc.direction}→${toNuc.helix_id}:${toNuc.bp_index}:${toNuc.direction}`,
            data: { fromNuc, toNuc, strand_id: hitStrandId },
          },
        })
      }
    } else {
      // ── Bead hit ────────────────────────────────────────────────────────
      const hitEntry = selBackbone.find(e => e.instMesh === beadHit0.object && e.id === beadHit0.instanceId)
      if (!hitEntry) return
      _handleBeadHit(hitEntry, backboneEntries, coneEntries, _prevOverhangId)
    }
  })

  // ── Right-click ──────────────────────────────────────────────────────────

  let _rightDownPos = null

  canvas.addEventListener('pointerdown', e => {
    if (e.button === 2 && !isDisabled?.()) _rightDownPos = { x: e.clientX, y: e.clientY }
  })

  canvas.addEventListener('contextmenu', e => {
    e.preventDefault()
    if (!_rightDownPos) return
    const moved = Math.hypot(e.clientX - _rightDownPos.x, e.clientY - _rightDownPos.y)
    _rightDownPos = null
    if (moved > 4) return

    // Hoisted cone hit-test — used to decide whether to divert multi-overhang
    // selections to the OH context menu, or fall through to the strand menu.
    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, _cam())

    const coneEntries = designRenderer.getConeEntries()
    const coneMeshes  = [...new Set(coneEntries.map(e => e.instMesh))]
    const coneHits    = raycaster.intersectObjects(coneMeshes)

    // Resolve cone hit once — used in multiple checks below.
    const hitCone = coneHits.length
      ? (coneEntries.find(c => c.instMesh === coneHits[0].object && c.id === coneHits[0].instanceId) ?? null)
      : null

    const backboneEntries = designRenderer.getBackboneEntries()
    const backboneMeshes  = [...new Set(backboneEntries.map(e => e.instMesh))]
    const beadHits        = raycaster.intersectObjects(backboneMeshes)
    const hitBead = beadHits.length
      ? (backboneEntries.find(b => b.instMesh === beadHits[0].object && b.id === beadHits[0].instanceId) ?? null)
      : null

    // Multi-selection right-click — dispatch to the appropriate menu.
    if (_multiLoopSkipEntries.length > 0) {
      _showMultiLoopSkipMenu(e.clientX, e.clientY)
      return
    }
    // Multi-overhang divert — UNLESS the click hits a strand cone, in which
    // case the strand menu wins (and gets an "Open Overhangs Manager" entry
    // injected via _ovhgMultiIds below).
    if (_multiOverhangIds.length > 0 && onOverhangRightClick && !hitCone) {
      onOverhangRightClick(_multiOverhangIds, e.clientX, e.clientY)
      return
    }
    if (_multiDomainIds.length > 0) {
      // Capture refs BEFORE any teardown; the menu's apply() rebuilds the scene
      // (clearing the lasso via the post-rebuild subscription).
      _showMultiDomainMenu(e.clientX, e.clientY, [..._multiDomainIds], designRenderer)
      return
    }
    if (_multiStrandIds.length > 0) {
      _showMultiMenu(e.clientX, e.clientY, _multiStrandIds, designRenderer)
      return
    }

    // A cluster is the active selection (click-drill landed on the cluster
    // level) → offer the move/rotate gizmo for it. Takes priority over the
    // per-strand color menu so a selected cluster is always actionable.
    if (_mode === 'cluster' && _drillClusterId && onClusterMoveRotate) {
      _showClusterMenu(e.clientX, e.clientY, _drillClusterId, onClusterMoveRotate)
      return
    }

    // Unpaired bead → flexible-segment menu (mark the contiguous ssDNA run as a
    // flexible tether). Fires when the click lands directly on an unpaired bead
    // that is frontmost over any terminal cone, and the bead's strand isn't a
    // virtual linker. Falls through to the existing flows otherwise.
    const _beadFrontmost = hitBead && (!coneHits.length || beadHits[0].distance <= coneHits[0].distance)
    if (_beadFrontmost && hitBead.nuc?.is_unpaired && onFlexibleSegmentRightClick
        && !linkerConnectionForStrandId(hitBead.nuc.strand_id)) {
      _showFlexibleSegmentMenu(e.clientX, e.clientY, hitBead.nuc, onFlexibleSegmentRightClick)
      return
    }

    // Right-click on a rendered flexible arc (its beads are excluded from the
    // rigid meshes, so they aren't in hitBead) → unmark that segment.
    if (!_beadFrontmost && onFlexibleSegmentRightClick) {
      const flexConnId = getFlexibleArcs?.()?.hitTest?.(e.clientX, e.clientY, _cam(), canvas)
      if (flexConnId) {
        _showFlexibleConnectionMenu(e.clientX, e.clientY, flexConnId, onFlexibleSegmentRightClick)
        return
      }
    }

    // Snapshot the multi-overhang state for downstream menu rendering.
    const _ovhgMultiIds = (_multiOverhangIds.length === 1 || _multiOverhangIds.length === 2)
      ? [..._multiOverhangIds]
      : null

    // Right-click on any part of a linker strand (complement bead, bridge
    // bead, or strand cone) → full strand context menu with the Linker
    // section (Relax, Delete linker) at the top. `_showColorMenu` detects the
    // linker strand and prepends linker-specific items automatically.
    const directLinkerStrandId = hitCone?.strandId ?? hitBead?.nuc?.strand_id ?? null
    if (linkerConnectionForStrandId(directLinkerStrandId)) {
      _showColorMenu(e.clientX, e.clientY, directLinkerStrandId, designRenderer, _multiStrandIds, null, _ovhgMultiIds, onOpenOverhangsManager)
      return
    }

    // In bead mode, right-clicking always shows the loop/skip menu for the selected bead.
    if (_mode === 'bead' && _beadEntry?.nuc && onLoopSkip) {
      _showLoopSkipMenu(e.clientX, e.clientY, _beadEntry.nuc, onLoopSkip)
      return
    }

    // Compute overhang opts once — passed to _showColorMenu when domain mode has an overhang selected.
    let _ovhgOpts = null
    if (_mode === 'domain' && _strandId != null && _domainIndex != null) {
      const design = store.getState().currentDesign
      const dom = design?.strands?.find(s => s.id === _strandId)?.domains?.[_domainIndex]
      if (dom?.overhang_id) {
        if (onSetOverhangName) _ovhgOpts = { overhangId: dom.overhang_id, onSetName: onSetOverhangName }
        // Single-overhang right-click — dispatch to the overhang context menu,
        // UNLESS the cursor is actually over a crossover arc (e.g. the
        // stretched OH→parent crossover that the user wants to relax). In
        // that case yield to the arc-hit dispatch below so the user gets
        // Relax bond on the arc menu.
        const _rect_oh = canvas.getBoundingClientRect()
        const _arcOverlay = _findArcAt(e.clientX - _rect_oh.left, e.clientY - _rect_oh.top)
        const _arcHasXover = !!_arcOverlay?.crossover_id
        if (onOverhangRightClick && !_arcHasXover) {
          onOverhangRightClick([dom.overhang_id], e.clientX, e.clientY)
          return
        }
      }
    }

    // When a single DOMAIN is selected, scope the strand menu's Representation
    // submenu to that domain (captured before any menu teardown).
    const _domainRef = (_mode === 'domain' && _strandId != null && _domainIndex != null)
      ? { strandId: _strandId, domainIndex: _domainIndex }
      : null

    // If the click lands on the selected strand's own cone, show the color/delete menu immediately.
    // This must run before the overhang arrow check so that right-clicking a selected strand's
    // terminus always opens the strand menu, even when an extrude arrow is visible at that position.
    if ((_mode === 'strand' || _mode === 'domain') && hitCone?.strandId === _strandId) {
      _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager, _domainRef)
      return
    }

    // Check overhang arrow hit — only reached when the click is not on the selected strand's cone.
    if (onOverhangArrow) {
      const ol = getOverhangLocations?.()
      if (ol?.isVisible()) {
        const arrowEntry = ol.hitTest(raycaster)
        if (arrowEntry) {
          onOverhangArrow(arrowEntry, e.clientX, e.clientY)
          return
        }
      }
    }

    // Remaining cone hits: selected strand in bead mode (already handled above), or any
    // unselected strand — show nick menu.
    if (hitCone) {
      // Scaffold strand: always dispatch to the scaffold-specific menu regardless
      // of whether the strand is currently selected — avoids two inconsistent menus.
      if (onScaffoldRightClick) {
        const design = store.getState().currentDesign
        const strandType = design?.strands?.find(s => s.id === hitCone.strandId)?.strand_type
        if (strandType === 'scaffold') {
          onScaffoldRightClick(e.clientX, e.clientY, hitCone)
          return
        }
      }
      if ((_mode === 'strand' || _mode === 'domain' || _mode === 'bead') && hitCone.strandId === _strandId) {
        _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager, _domainRef)
        return
      }
      // Cone sits on an overhang domain — the strand already terminates there,
      // so "Nick here" is meaningless. Route to the overhang orientation menu
      // (which carries the Overhangs Manager entry).
      const coneOvhgId = hitCone.fromNuc?.overhang_id ?? hitCone.toNuc?.overhang_id
      if (coneOvhgId && onOverhangRightClick) {
        onOverhangRightClick([coneOvhgId], e.clientX, e.clientY)
        return
      }
      _showNickMenu(e.clientX, e.clientY, hitCone, onNick)
      return
    }

    // No visible cone hit — check arc proximity (cross-helix connections).
    // Arc lines are rendered exclusively by unfold_view.js.
    const linkHit = getOverhangLinkArcs?.()?.hitTest?.(e.clientX, e.clientY, _cam(), canvas)
    if (linkHit?.strandId) {
      _showColorMenu(e.clientX, e.clientY, linkHit.strandId, designRenderer, _multiStrandIds, null, _ovhgMultiIds, onOpenOverhangsManager)
      return
    }

    const rect3 = canvas.getBoundingClientRect()
    const arcHit = _findArcAt(e.clientX - rect3.left, e.clientY - rect3.top)
    if (arcHit?.fromNuc) {
      // ARC right-click: the user is acting on the bond itself (extra bases,
      // relax-bond), so the crossover/ligation menu wins over the
      // selected-strand color menu. Crossover-id check comes FIRST so that
      // the OH→parent crossover surfaces the Relax bond submenu even when
      // the OH-bearing strand happens to be the current selection.
      if (arcHit.crossover_id && onCrossoverRightClick) {
        const design = store.getState().currentDesign
        const xo = design?.crossovers?.find(x => x.id === arcHit.crossover_id)
        if (xo) { _showCrossoverMenu(e.clientX, e.clientY, xo, onCrossoverRightClick); return }
        const fl = design?.forced_ligations?.find(f => f.id === arcHit.crossover_id)
        if (fl) { _showCrossoverMenu(e.clientX, e.clientY, fl, onCrossoverRightClick); return }
      }
      // No crossover/ligation record on this arc — fall back to the strand
      // color/isolate menu when the arc belongs to the currently selected
      // strand. This keeps the "isolate from arc" flow working for
      // intra-strand arcs that have no associated record.
      if ((_mode === 'strand' || _mode === 'domain' || _mode === 'bead') && arcHit.strandId === _strandId) {
        _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager, _domainRef)
        return
      }
      return
    }

    if (_mode === 'none' || !_strandId) {
      // Nothing hit and nothing selected → right-click landed on empty 3D
      // space. Surface the empty-space context menu (e.g. "Extrude" to start a
      // new bundle). The callback owns its own mode/visibility guards.
      onEmptyContextMenu?.(e.clientX, e.clientY)
      return
    }
    _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager, _domainRef)
  })

  // ── Re-apply highlights after scene rebuild ──────────────────────────────

  store.subscribe((newState, prevState) => {
    // Any change that triggers a design_renderer rebuild (geometry, design topology,
    // strandGroups) invalidates our cached entry references and clears glow.
    // Re-apply highlights so they survive view transitions and cross-tab syncs.
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.currentDesign   === prevState.currentDesign   &&
        newState.strandGroups    === prevState.strandGroups) return
    _strandEntries     = []
    _strandConeEntries = []
    _strandArcEntries  = []
    _beadEntry         = null
    _coneEntry         = null
    // Re-apply multi-selection highlights after rebuild (entry references are stale)
    _multiEntries       = []
    _multiConeEntries   = []
    _multiDomainEntries = []
    _multiOverhangEntries = []
    if (_multiOverhangIds.length > 0) {
      const validOverhangIds = new Set((newState.currentDesign?.overhangs ?? []).map(o => o.id))
      _multiOverhangIds = _multiOverhangIds.filter(id => validOverhangIds.has(id))
    }
    if (_multiStrandIds.length > 0)   _applyMultiHighlight(_multiStrandIds)
    if (_multiDomainIds.length > 0)   _applyMultiDomainHighlight(_multiDomainIds)
    if (_multiOverhangIds.length > 0) _applyMultiOverhangHighlight(_multiOverhangIds)
    // Ctrl-selected beads become stale after a rebuild — clear them
    if (_ctrlBeads.length > 0) { _ctrlBeads = []; _notifyCtrlBeadsChange() }

    const backboneEntries = designRenderer.getBackboneEntries()
    const coneEntries     = designRenderer.getConeEntries()

    if (_mode === 'strand' && _strandId) {
      _highlightStrand(backboneEntries, coneEntries, _strandId)

    } else if (_mode === 'bead' && _strandId) {
      _highlightStrand(backboneEntries, coneEntries, _strandId)
      const sel = newState.selectedObject?.data
      if (sel) {
        const found = backboneEntries.find(e =>
          e.nuc.helix_id  === sel.helix_id  &&
          e.nuc.bp_index  === sel.bp_index  &&
          e.nuc.direction === sel.direction
        )
        if (found) _highlightBead(found)
        else {
          _mode = 'strand'
          store.setState({ selectedObject: _strandSelection(_strandId) })
        }
      }

    } else if (_mode === 'cone' && _strandId) {
      _highlightStrand(backboneEntries, coneEntries, _strandId)
      const sel = newState.selectedObject?.data
      if (sel?.fromNuc) {
        const found = coneEntries.find(e =>
          e.fromNuc.helix_id  === sel.fromNuc.helix_id  &&
          e.fromNuc.bp_index  === sel.fromNuc.bp_index  &&
          e.fromNuc.direction === sel.fromNuc.direction
        )
        if (found) _highlightCone(found)
        else {
          _mode = 'strand'
          store.setState({ selectedObject: _strandSelection(_strandId) })
        }
      }

    } else if (_mode === 'domain' && _strandId) {
      // Re-apply domain highlight (incl. cylinder glow) — e.g. after converting
      // this domain to/from a cylinder, which rebuilds the scene.
      _highlightStrand(backboneEntries, coneEntries, _strandId)
      const di = newState.selectedObject?.data?.domain_index
      if (di != null) _highlightDomain(di)

    } else if (_mode === 'cluster' && _drillClusterId) {
      _highlightCluster(_drillClusterId, backboneEntries)

    } else {
      _mode = 'none'
      store.setState({ selectedObject: null })
    }
  })

  return {
    /** Programmatically select a strand by ID, applying the same 3D highlight
     *  as a manual bead click (white beads at 1.3× scale). */
    selectStrand(strandId) {
      const backboneEntries = designRenderer.getBackboneEntries()
      const coneEntries     = designRenderer.getConeEntries()
      _mode     = 'strand'
      _strandId = strandId
      _coneEntry = null
      _highlightStrand(backboneEntries, coneEntries, strandId)
      store.setState({ selectedObject: _strandSelection(strandId) })
    },

    /** Programmatically select an individual nucleotide (as if double-clicked in bead mode).
     *  Looks up the current backbone entry for the nuc, highlights the strand + bead,
     *  and updates selectedObject.  No-op if no matching entry exists. */
    selectNucleotide(nuc) {
      const backboneEntries = designRenderer.getBackboneEntries()
      const coneEntries     = designRenderer.getConeEntries()
      const entry = backboneEntries.find(e =>
        e.nuc.helix_id  === nuc.helix_id &&
        e.nuc.bp_index  === nuc.bp_index &&
        e.nuc.direction === nuc.direction,
      )
      if (!entry) return
      _restoreStrand()
      _mode     = 'bead'
      _strandId = nuc.strand_id
      _highlightStrand(backboneEntries, coneEntries, nuc.strand_id)
      _highlightBead(entry)
      store.setState({
        selectedObject: {
          type: 'nucleotide',
          id:   `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`,
          data: nuc,
        },
      })
    },

    /** Reset the auto-drill cursor (level + anchor). Called when the user pins a
     *  manual filter or presses Tab so the auto-state stops fighting the manual
     *  selection. Does not clear the current highlight. */
    resetDrill() { _resetDrill(); _emitDrillLevel(null) },

    /** Tab drill-lock: pin the auto-drill to a fixed level so every click selects
     *  at that level (no descent). Pass null to return to normal auto-drill.
     *  Emits the level so the matching filter button reflects the lock. */
    setDrillLock(level) {
      _drillLock = level || null
      _resetDrill()
      _emitDrillLevel(_drillLock)
    },
    /** The active Tab drill-lock level, or null when in normal auto-drill. */
    getDrillLock() { return _drillLock },

    /** Drill-v2: is the unified selectionLevel model active (NADOC_DRILL_V2)? */
    isDrillV2() { return _drillV2 },
    /** Drill-v2: the active selectionLevel ('default'|'cluster'|'domain'|'end'|'xover'). */
    getSelectionLevel() { return _selLevel },
    /** Drill-v2: set the active selectionLevel; emits it so the filter row reflects.
     *  Returning to 'default' drops any hover preview. */
    setSelectionLevel(level) {
      _selLevel = normalizeLevel(level)
      if (_selLevel !== 'default') _clearHoverPreview()
      _emitDrillLevel(_selLevel)
      return _selLevel
    },

    /** Returns a copy of the current ctrl-click nucleotide selection. */
    getCtrlBeads() { return [..._ctrlBeads] },

    /** Returns the world-space THREE.Vector3 for the nth ctrl-selected bead (0-indexed). */
    getCtrlBeadPos(n) { return _ctrlBeads[n]?.entry.pos.clone() ?? null },

    /** Register a callback fired whenever _ctrlBeads changes. Multiple subscribers allowed. */
    onCtrlBeadsChange(fn) { _ctrlBeadsChangeCbs.push(fn) },

    /** Programmatically clear all ctrl-selected beads. */
    clearCtrlBeads() { _clearCtrlBeads() },

    /** Programmatically apply multi-strand highlight from a cross-window broadcast.
     *  Replaces any existing multi-selection. Pass [] to clear. */
    setMultiHighlight(strandIds) {
      if (strandIds.length === 0) {
        _clearMultiSelection()
      } else {
        _applyMultiHighlight(strandIds)
        store.setState({ multiSelectedStrandIds: strandIds })
      }
    },

    /** Returns the current multi-selected crossover arc entries. */
    getMultiCrossoverArcs() { return [..._multiCrossoverArcs] },

    /** Clear multi-crossover arc selection, restoring default arc colors. */
    clearMultiCrossoverArcs() { _clearMultiCrossoverArcs() },

    /** Clear selected overhang highlights. */
    clearMultiOverhangSelection() { _clearMultiOverhangSelection() },
  }
}
