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
 * Ctrl+left-click (no drag) → toggle backbone bead in _ctrlBeads (distance measurement).
 * Ctrl+left-drag             → rectangle lasso multi-select.
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
  if (!confirm(`Delete entire linker "${linkerLabel(conn)}"?`)) return
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
const _arcHitPx  = 12   // screen-space proximity threshold for arc midpoint hits

// ── Context menu ──────────────────────────────────────────────────────────────

let _menuEl = null


function _dismissMenu() {
  if (_menuEl) {
    _menuEl.remove()
    _menuEl = null
  }
}

function _menuOutsideListeners(menu) {
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
  return menu
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

function _showColorMenu(x, y, strandId, designRenderer, multiStrandIds = [], overhangOpts = null, ovhgMultiIds = null, onOpenOverhangsManager = null) {
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
  const isScaffold = design?.strands?.find(s => s.id === strandId)?.strand_type === 'scaffold'

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
  const { onNick, onLoopSkip, onOverhangArrow, onScaffoldRightClick, onCrossoverRightClick, onSetOverhangName, onOverhangRightClick, onOpenOverhangsManager, getUnfoldView, getOverhangLocations, getOverhangLinkArcs, getLoopSkipHighlight, controls, getHoverEntry, getCamera, isDisabled } = opts

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
    designRenderer.setGlowEntries([..._selectionGlowEntries, ..._ctrlBeads.map(b => b.entry)])
  }

  function _clearSelectionGlow() {
    _selectionGlowEntries = []
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
  function _handleCtrlClick(e) {
    const st = store.getState().selectableTypes
    if (st.crossoverArcs) {
      const rect = canvas.getBoundingClientRect()
      const arcHit = _findArcAt(e.clientX - rect.left, e.clientY - rect.top)
      if (arcHit?.crossover_id) {
        // Toggle this arc in the multi-crossover selection.
        const idx = _multiCrossoverArcs.findIndex(a => a.crossover_id === arcHit.crossover_id)
        if (idx >= 0) {
          // Deselect
          _multiCrossoverArcs[idx].setColor(_multiCrossoverArcs[idx].defaultColor)
          _multiCrossoverArcs.splice(idx, 1)
        } else {
          // Select
          arcHit.setColor(C_MULTI_XOVER_ARC)
          _multiCrossoverArcs.push(arcHit)
        }
        getUnfoldView?.()?.updateArcGlow(_multiCrossoverArcs)
        return
      }
    }
    _handleCtrlClickNuc(e)
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
    const endEntries    = []   // end beads captured by the ends filter → go to _ctrlBeads

    const st = store.getState().selectableTypes
    const cylMesh = designRenderer.getCylinderMesh()
    const inCylinderLOD = cylMesh?.visible ?? false

    // ── Cylinder LOD strands ───────────────────────────────────────────────
    // When iHelixCylinders is visible, project each cylinder center into screen
    // space and collect strand IDs that fall inside the lasso rect.
    // Bead iteration is skipped — beads are hidden in this mode.
    if (inCylinderLOD && st.strands) {
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

      // Ends filter captures individual beads into _ctrlBeads (handled below).
      if (typeAllowed && st.ends && isEnd) {
        endEntries.push(entry)
      }

      // Strands capture whole strands into the multi-select set.
      if (typeAllowed && st.strands) {
        strandIdSet.add(entry.nuc.strand_id)
      }

      // Domains capture per-domain groups.
      if (typeAllowed && st.domains) {
        const k = `${entry.nuc.strand_id}:${entry.nuc.domain_index ?? 0}`
        if (!domainKeyMap.has(k)) {
          domainKeyMap.set(k, { strandId: entry.nuc.strand_id, domainIndex: entry.nuc.domain_index ?? 0 })
        }
      }

      // Overhangs capture by overhang_id (independent — no scaffold/staple filter).
      if (st.overhangs && entry.nuc.overhang_id) {
        ovhangIdSet.add(entry.nuc.overhang_id)
      }
    }
    }

    // ── Loop/skip markers ──────────────────────────────────────────────────
    if (st.loops || st.skips) {
      const lsh = getLoopSkipHighlight?.()
      if (lsh) {
        const newLsEntries = []
        for (const e of lsh.getEntries()) {
          if (e.type === 'loop' && !st.loops) continue
          if (e.type === 'skip' && !st.skips) continue
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
    if (st.crossoverArcs) {
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

  // Capture-phase: disable controls before OrbitControls sees Ctrl+left so it
  // cannot start a pan gesture that competes with the lasso drag.
  canvas.addEventListener('pointerdown', e => {
    if (e.button === 0 && e.ctrlKey && controls) controls.enabled = false
  }, { capture: true })

  let _downPos     = null
  let _ctrlDownPos = null   // pending ctrl+left-down — becomes lasso (drag) or nucleotide pick (click)

  canvas.addEventListener('pointerdown', e => {
    if (e.button !== 0) return
    if (isDisabled?.()) return

    // Ctrl+left — defer: determine on move/up whether this is a lasso drag or a nucleotide pick
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
      _finalizeLasso(e.clientX, e.clientY)
      return
    }

    // Ctrl+left click (no drag) → toggle arc/loop-skip/nucleotide selection
    if (_ctrlDownPos) {
      const moved = Math.hypot(e.clientX - _ctrlDownPos.x, e.clientY - _ctrlDownPos.y)
      _ctrlDownPos = null
      if (moved <= 4) _handleCtrlClick(e)
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

    // In cylinder LOD, beads and cones are hidden — skip their raycasting entirely.
    const _inCylinderLOD = designRenderer.getCylinderMesh()?.visible ?? false

    // Respect selection filter
    const selBackbone = _inCylinderLOD ? [] : backboneEntries.filter(e => {
      if (selectableTypes.overhangs && e.nuc.overhang_id) return true
      const isScaffold = e.nuc.strand_type === 'scaffold'
      const isEnd      = e.nuc.is_five_prime || e.nuc.is_three_prime
      if (!(isScaffold ? selectableTypes.scaffold : selectableTypes.staples)) return false
      if (selectableTypes.ends && isEnd) return true
      return selectableTypes.strands || selectableTypes.domains
    })
    const selCones = _inCylinderLOD ? [] : coneEntries.filter(e => {
      if (!selectableTypes.strands) return false
      const isScaf = e.fromNuc?.strand_type === 'scaffold'
      return isScaf ? selectableTypes.scaffold : selectableTypes.staples
    })

    // Raycast against all unique InstancedMeshes, then find the closest
    // intersection whose instanceId belongs to a selectable entry.
    const beadMeshes = _inCylinderLOD ? [] : [...new Set(backboneEntries.map(e => e.instMesh))]
    const coneMeshes = _inCylinderLOD ? [] : [...new Set(coneEntries.map(e => e.instMesh))]

    const allBeadHits = beadMeshes.length ? raycaster.intersectObjects(beadMeshes) : []
    const allConeHits = coneMeshes.length ? raycaster.intersectObjects(coneMeshes) : []

    const beadHit0 = allBeadHits.find(h =>
      selBackbone.some(e => e.instMesh === h.object && e.id === h.instanceId))
    const coneHit0 = allConeHits.find(h =>
      selCones.some(e => e.instMesh === h.object && e.id === h.instanceId))

    const beadDist = beadHit0?.distance ?? Infinity
    const coneDist = coneHit0?.distance ?? Infinity

    // ── Cylinder LOD hit (only active when iHelixCylinders is visible) ───────
    if (beadDist === Infinity && coneDist === Infinity && selectableTypes.strands) {
      const cylMesh = designRenderer.getCylinderMesh()
      if (cylMesh?.visible) {
        const cylHits = raycaster.intersectObjects([cylMesh])
        const cylHit0 = cylHits[0]
        if (cylHit0 != null) {
          const dom = designRenderer.getCylinderDomainAt(cylHit0.instanceId)
          if (dom?.strandId) {
            const design = store.getState().currentDesign
            const strand = design?.strands?.find(s => s.id === dom.strandId)
            const isScaffold = strand?.strand_type === 'scaffold'
            if (isScaffold ? selectableTypes.scaffold : selectableTypes.staples) {
              const hitStrandId = dom.strandId
              _restoreStrand()       // clear any bead-mode selection
              if (_cylStrandId !== hitStrandId) {
                _clearCylinderSelection()
                _cylStrandId = hitStrandId
                _mode        = 'cylinder'
                _strandId    = hitStrandId
                designRenderer.highlightCylinderStrands([hitStrandId])
                store.setState({ selectedObject: _strandSelection(hitStrandId) })
              } else {
                // Second click same strand → deselect
                _clearAll()
              }
              return
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
          const glowEntries = designRenderer.getCrossoverGlowEntries(target)
          _setSelectionGlow(glowEntries)
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
      const hitStrandId = hitEntry.nuc.strand_id

      // ── Overhang filter active → select at overhang granularity ────────────
      if (selectableTypes.overhangs && hitEntry.nuc.overhang_id) {
        const ovhgId = hitEntry.nuc.overhang_id
        if (_prevOverhangId !== ovhgId) {
          _applyMultiOverhangHighlight([ovhgId])
          store.setState({ multiSelectedOverhangIds: [ovhgId] })
        }
        // If same overhang clicked again → already cleared above → leave deselected
        return
      }

      // ── Domain filter active → select at domain granularity ─────────────
      if (selectableTypes.domains) {
        const domainIdx = hitEntry.nuc.domain_index ?? 0
        if (_mode === 'domain' && _strandId === hitStrandId && _domainIndex === domainIdx) {
          // Same domain clicked again → deselect
          _clearAll()
        } else {
          // New domain (same or different strand) → select it
          _restoreStrand()
          _mode     = 'domain'
          _strandId = hitStrandId
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

      if (_mode === 'none' || hitStrandId !== _strandId) {
        // New strand → select strand
        _mode      = 'strand'
        _strandId  = hitStrandId
        _coneEntry = null
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        store.setState({
          selectedObject: _strandSelection(
            hitStrandId ?? `unassigned:${hitEntry.nuc.helix_id}:${hitEntry.nuc.direction}`,
            { helix_id: hitEntry.nuc.helix_id },
          ),
        })
      } else if (_mode === 'strand') {
        // Second click on same strand → select individual nucleotide
        _mode = 'bead'
        _highlightBead(hitEntry)
        store.setState({
          selectedObject: {
            type: 'nucleotide',
            id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
            data: hitEntry.nuc,
          },
        })
      } else if (
        _mode === 'bead' && _beadEntry &&
        _beadEntry.nuc.helix_id  === hitEntry.nuc.helix_id &&
        _beadEntry.nuc.bp_index  === hitEntry.nuc.bp_index &&
        _beadEntry.nuc.direction === hitEntry.nuc.direction
      ) {
        // Same bead clicked while already in bead mode → deselect
        _clearAll()
      } else {
        // Different bead in bead mode → select that bead
        _mode = 'bead'
        _highlightBead(hitEntry)
        store.setState({
          selectedObject: {
            type: 'nucleotide',
            id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
            data: hitEntry.nuc,
          },
        })
      }
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
      _clearMultiDomainSelection()
      // Fall through — show strand menu if one is selected
    }
    if (_multiStrandIds.length > 0) {
      _showMultiMenu(e.clientX, e.clientY, _multiStrandIds, designRenderer)
      return
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
        // Single-overhang right-click — dispatch to the overhang context menu.
        if (onOverhangRightClick) {
          onOverhangRightClick([dom.overhang_id], e.clientX, e.clientY)
          return
        }
      }
    }

    // If the click lands on the selected strand's own cone, show the color/delete menu immediately.
    // This must run before the overhang arrow check so that right-clicking a selected strand's
    // terminus always opens the strand menu, even when an extrude arrow is visible at that position.
    if ((_mode === 'strand' || _mode === 'domain') && hitCone?.strandId === _strandId) {
      _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager)
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
        _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager)
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
      // In strand, domain, or bead mode, right-clicking the selected strand's arc shows the color/isolate menu
      if ((_mode === 'strand' || _mode === 'domain' || _mode === 'bead') && arcHit.strandId === _strandId) {
        _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager)
        return
      }
      // Arc hit has a crossover_id — show the crossover context menu.
      // The id may belong to a regular Crossover or a ForcedLigation.
      if (arcHit.crossover_id && onCrossoverRightClick) {
        const design = store.getState().currentDesign
        const xo = design?.crossovers?.find(x => x.id === arcHit.crossover_id)
        if (xo) { _showCrossoverMenu(e.clientX, e.clientY, xo, onCrossoverRightClick); return }
        // Fall through to forced ligations.
        const fl = design?.forced_ligations?.find(f => f.id === arcHit.crossover_id)
        if (fl) { _showCrossoverMenu(e.clientX, e.clientY, fl, onCrossoverRightClick); return }
      }
      return
    }

    if (_mode === 'none' || !_strandId) return
    _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer, _multiStrandIds, _ovhgOpts, _ovhgMultiIds, onOpenOverhangsManager)
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
