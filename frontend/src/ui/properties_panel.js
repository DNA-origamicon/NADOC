/**
 * Properties panel — shows selected object details in the right panel.
 *
 * Subscribes to canonical selection and resolves rich display data from the design.
 *
 * Display modes (by displayObject.type):
 *   strand     — per-strand summary (length nt, domains, helix coverage)
 *   domain     — per-domain detail (helix, range, direction, overhang flag)
 *   nucleotide — per-bead detail (helix, bp, backbone/base positions)
 *   cone       — connector between two nucleotides
 *   crossover  — half-A/half-B + extra bases
 *   cluster    — helix count + default/sub-cluster
 *   protein    — imported-protein attachment (asset name, anchor, atom/residue/chain counts)
 */

import { store } from '../state/store.js'
import * as api from '../api/client.js'
import { BDNA_RISE_PER_BP } from '../constants.js'
import { parseBaseKey } from '../scene/base_ref.js'
import {
  canonicalSelection, overhangSelectionTarget, extensionSelectionTarget,
} from '../scene/selection_model.js'
import {
  buildStrandDisplayIdMap, helixDisplayLabel, helixDisplayLabels,
  selectedBaseDisplayRows, strandDisplayId,
} from './design_display_labels.js'

export function initPropertiesPanel({ clearSelection } = {}) {
  const content = document.getElementById('properties-content')
  if (!content) return

  function _fmt(arr) {
    return arr.map(v => Number(v.toFixed(4))).join(', ')
  }

  function _strandLength(strand, design) {
    const helixById = Object.fromEntries((design?.helices ?? []).map(h => [h.id, h]))
    let total = 0
    for (const domain of strand.domains) {
      const span = Math.abs(domain.end_bp - domain.start_bp) + 1
      const helix = helixById[domain.helix_id]
      const lo = Math.min(domain.start_bp, domain.end_bp)
      const hi = Math.max(domain.start_bp, domain.end_bp)
      const skipDelta = helix?.loop_skips
        ?.filter(ls => ls.bp_index >= lo && ls.bp_index <= hi)
        ?.reduce((s, ls) => s + ls.delta, 0) ?? 0
      total += span + skipDelta
    }
    return total
  }

  function _strandTypeTag(type) {
    if (type === 'scaffold') return '<span class="tag tag-scaffold">scaffold</span>'
    if (type === 'linker') return '<span class="tag" style="background:#ffffff;color:#111">linker</span>'
    return '<span class="tag tag-staple">staple</span>'
  }

  function _linkerConnectionForStrand(strandId, design) {
    const m = /^__lnk__(.+)__(a|b)$/.exec(strandId ?? '')
    if (!m) return null
    return design?.overhang_connections?.find(c => c.id === m[1]) ?? null
  }

  function _linkerBridgeBases(conn) {
    const value = Number(conn?.length_value)
    if (!Number.isFinite(value) || value <= 0) return 0
    return conn.length_unit === 'nm'
      ? Math.max(1, Math.round(value / BDNA_RISE_PER_BP))
      : Math.max(1, Math.round(value))
  }

  function _renderStrand(displayObject) {
    const design = store.getState().currentDesign
    const strandId = displayObject.data?.strand_id
    if (!design || !strandId) {
      content.innerHTML = `<span class="dim">Strand selected.</span>`
      return
    }

    // Each strand IS the complete oligo — crossover ligation is done server-side.
    const strand = design.strands.find(s => s.id === strandId)
    if (!strand) {
      content.innerHTML = `<span class="dim">Strand not found in design.</span>`
      return
    }

    const conn = _linkerConnectionForStrand(strandId, design)
    const displayIds = buildStrandDisplayIdMap(design.strands)
    const displayId = displayIds.get(strandId) ?? '—'
    const logicalStrands = conn?.linker_type === 'ss'
      ? [`__lnk__${conn.id}__a`, `__lnk__${conn.id}__b`]
          .map(id => design.strands.find(s => s.id === id))
          .filter(Boolean)
      : [strand]
    const bridgeNt    = conn?.linker_type === 'ss' ? _linkerBridgeBases(conn) : 0
    const lengthNt    = logicalStrands.reduce((sum, s) => sum + _strandLength(s, design), 0) + bridgeNt
    const domainCount = logicalStrands.reduce((sum, s) => sum + s.domains.length, 0)
    const helixIds    = [...new Set(logicalStrands.flatMap(s => s.domains.map(d => d.helix_id)))]
    const helixLabels = helixDisplayLabels(design, helixIds)
    const segmentCount = 1

    const typeTag = _strandTypeTag(strand.strand_type)
    const linkerNote = conn
      ? `<div class="prop-row"><span class="prop-label">linker</span><span class="prop-val">${conn.name ?? conn.id} · ${conn.linker_type}DNA · ${conn.length_value} ${conn.length_unit}${bridgeNt ? ` (${bridgeNt} bridge nt)` : ''}</span></div>`
      : ''

    const segmentNote = segmentCount > 1
      ? `<div class="prop-row"><span class="prop-label">segments</span><span class="prop-val">${segmentCount} (joined by crossover${segmentCount > 2 ? 's' : ''})</span></div>`
      : ''

    // Domain rows — each strand IS the complete oligo (crossover ligation is server-side).
    let domainIdx = 0
    const domainRows = logicalStrands.flatMap(s => s.domains.map(d => {
      const i   = domainIdx++
      const len = Math.abs(d.end_bp - d.start_bp) + 1
      return `<div class="prop-row" style="padding-left:8px">
        <span class="prop-label" style="min-width:18px">${i}</span>
        <span class="prop-val mono">${displayIds.get(s.id) ?? '—'} · ${helixDisplayLabel(design, d.helix_id)} · ${d.start_bp}→${d.end_bp} (${len} bp) ${d.direction}</span>
      </div>`
    })).join('')

    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">strand</span>
        <span class="prop-val">${displayId}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">type</span>
        ${typeTag}
      </div>
      ${linkerNote}
      <div class="prop-row">
        <span class="prop-label">length</span>
        <span class="prop-val">${lengthNt} nt</span>
      </div>
      ${segmentNote}
      <div class="prop-row">
        <span class="prop-label">domains</span>
        <span class="prop-val">${domainCount}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">helices</span>
        <span class="prop-val">${helixLabels.join(', ')}</span>
      </div>
      <details style="margin-top:6px; border-top:1px solid #21262d; padding-top:4px">
        <summary style="cursor:pointer; margin-bottom:3px">
          <span class="prop-label">domains</span>
        </summary>
        ${domainRows}
      </details>
    `
  }

  function _renderNucleotide(displayObject) {
    const nuc = displayObject.data
    const design = store.getState().currentDesign
    const helix  = design?.helices?.find(h => h.id === nuc.helix_id)

    const scaffoldTag = _strandTypeTag(nuc.strand_type)

    const endTag = nuc.is_five_prime
      ? "<span class=\"tag tag-end\">5′ end</span>"
      : nuc.is_three_prime
        ? "<span class=\"tag tag-end\">3′ end</span>"
        : ''

    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">helix</span>
        <span class="prop-val">${helixDisplayLabel(design, nuc.helix_id)}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">bp</span>
        <span class="prop-val">${nuc.bp_index}</span>
        <span class="prop-label" style="margin-left:8px">dir</span>
        <span class="prop-val">${nuc.direction}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">strand</span>
        <span class="prop-val">${nuc.strand_id ?? '—'}</span>
        ${scaffoldTag} ${endTag}
      </div>
      <div class="prop-row">
        <span class="prop-label">backbone</span>
        <span class="prop-val mono">[${_fmt(nuc.backbone_position)}]</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">base&nbsp;&nbsp;&nbsp;</span>
        <span class="prop-val mono">[${_fmt(nuc.base_position)}]</span>
      </div>
      ${helix ? `
      <div class="prop-row" style="margin-top:6px; border-top:1px solid #21262d; padding-top:6px">
        <span class="prop-label">helix len</span>
        <span class="prop-val">${helix.length_bp} bp</span>
      </div>
      <button class="danger-btn" id="delete-helix-btn">Delete helix</button>
      ` : ''}
    `

    const delBtn = content.querySelector('#delete-helix-btn')
    if (delBtn) {
      delBtn.addEventListener('click', async () => {
        const r = await api.deleteHelix(nuc.helix_id)
        if (!r) {
          const err = store.getState().lastError
          alert(`Cannot delete helix: ${err?.message}`)
        } else {
          clearSelection?.()
        }
      })
    }
  }

  function _renderDomain(displayObject) {
    const design = store.getState().currentDesign
    const { strand_id, domain_index, helix_id, direction, overhang_id } = displayObject.data ?? {}
    const strand = design?.strands?.find(s => s.id === strand_id)
    const domain = strand?.domains?.[domain_index]

    if (!domain) {
      content.innerHTML = `<span class="dim">Domain selected.</span>`
      return
    }

    const len = Math.abs(domain.end_bp - domain.start_bp) + 1
    const typeTag = _strandTypeTag(strand.strand_type)
    const ovhgTag = overhang_id
      ? `<span class="tag" style="background:#f5a623;color:#000">overhang</span>`
      : ''

    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">domain</span>
        <span class="prop-val">#${domain_index}</span>
        ${typeTag} ${ovhgTag}
      </div>
      <div class="prop-row">
        <span class="prop-label">helix</span>
        <span class="prop-val">${helixDisplayLabel(design, helix_id)}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">range</span>
        <span class="prop-val">${domain.start_bp} → ${domain.end_bp}  (${len} bp)</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">dir</span>
        <span class="prop-val">${direction}</span>
      </div>
      ${overhang_id ? `
      <div class="prop-row">
        <span class="prop-label">ovhg id</span>
        <span class="prop-val mono" style="font-size:var(--text-xs)">${overhang_id}</span>
      </div>` : ''}
      <div class="prop-row" style="margin-top:4px">
        <span class="prop-label">strand</span>
        <span class="prop-val">${strandDisplayId(strand_id, design)}</span>
      </div>
    `
  }

  function _renderOverhang(displayObject) {
    const d = displayObject.data ?? {}
    const sequence = d.sequence || '—'
    const domainRange = d.domain
      ? `${d.domain.start_bp} → ${d.domain.end_bp}`
      : '—'
    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">overhang</span>
        <span class="prop-val">${d.label || displayObject.id}</span>
        <span class="tag" style="background:#f5a623;color:#000">overhang</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">sequence</span>
        <span class="prop-val mono">${sequence}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">domain</span>
        <span class="prop-val">${d.domainIndex == null ? '—' : `#${d.domainIndex} (${domainRange})`}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">strand</span>
        <span class="prop-val">${strandDisplayId(d.strandId, store.getState().currentDesign)}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">id</span>
        <span class="prop-val mono" style="font-size:var(--text-xs)">${displayObject.id}</span>
      </div>
    `
  }

  function _renderExtension(displayObject) {
    const d = displayObject.data ?? {}
    const end = d.end === 'five_prime' ? '5′' : d.end === 'three_prime' ? '3′' : '—'
    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">extension</span>
        <span class="prop-val">${d.label || displayObject.id}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">end</span>
        <span class="prop-val">${end}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">sequence</span>
        <span class="prop-val mono">${d.sequence || '—'}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">modification</span>
        <span class="prop-val">${d.modification || '—'}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">strand</span>
        <span class="prop-val">${strandDisplayId(d.strandId, store.getState().currentDesign)}</span>
      </div>
    `
  }

  function _renderCrossover(displayObject) {
    const xo = displayObject.data
    if (!xo) { content.innerHTML = '<span class="dim">Crossover selected.</span>'; return }
    const design = store.getState().currentDesign
    const extraLabel = xo.extra_bases
      ? `"${xo.extra_bases}" (${xo.extra_bases.length} nt)`
      : 'none'
    if (displayObject.type === 'forced_ligation') {
      content.innerHTML = `
        <div class="prop-row">
          <span class="prop-label">forced ligation</span>
          <span class="prop-val mono" style="font-size:var(--text-xs)">${xo.id}</span>
        </div>
        <div class="prop-row">
          <span class="prop-label">3′ end</span>
          <span class="prop-val mono">${helixDisplayLabel(design, xo.three_prime_helix_id)} · bp ${xo.three_prime_bp} ${xo.three_prime_direction}</span>
        </div>
        <div class="prop-row">
          <span class="prop-label">5′ end</span>
          <span class="prop-val mono">${helixDisplayLabel(design, xo.five_prime_helix_id)} · bp ${xo.five_prime_bp} ${xo.five_prime_direction}</span>
        </div>
        <div class="prop-row">
          <span class="prop-label">extra bases</span>
          <span class="prop-val">${extraLabel}</span>
        </div>
      `
      return
    }
    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">crossover</span>
        <span class="prop-val mono" style="font-size:var(--text-xs)">${xo.id}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">half A</span>
        <span class="prop-val mono">${helixDisplayLabel(design, xo.half_a.helix_id)} · bp ${xo.half_a.index} ${xo.half_a.strand}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">half B</span>
        <span class="prop-val mono">${helixDisplayLabel(design, xo.half_b.helix_id)} · bp ${xo.half_b.index} ${xo.half_b.strand}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">extra bases</span>
        <span class="prop-val">${extraLabel}</span>
      </div>
    `
  }

  function _renderBond(displayObject) {
    content.innerHTML = `
      <div class="prop-row"><span class="prop-label">bond</span><span class="prop-val">backbone</span></div>
      <div class="prop-row"><span class="prop-label">from</span><span class="prop-val mono">${displayObject.data.fromKey}</span></div>
      <div class="prop-row"><span class="prop-label">to</span><span class="prop-val mono">${displayObject.data.toKey}</span></div>
    `
  }

  function _renderCluster(displayObject) {
    const d = displayObject.data ?? {}
    const helixCount = d.helix_ids?.length ?? 0
    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">cluster</span>
        <span class="prop-val mono" style="font-size:var(--text-xs)">${(displayObject.id ?? '').slice(0, 8)}…</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">helices</span>
        <span class="prop-val">${helixCount}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">type</span>
        <span class="prop-val">${d.is_default ? 'default (all helices)' : 'sub-cluster'}</span>
      </div>
    `
  }

  function _renderProtein(displayObject) {
    const design = store.getState().currentDesign
    const attId  = displayObject.id ?? displayObject.data?.attachment_id
    const att    = design?.protein_attachments?.find(a => a.id === attId)
    if (!att) {
      content.innerHTML = `<span class="dim">Protein selected.</span>`
      return
    }
    const asset = design?.protein_assets?.find(a => a.id === att.asset_id)
    const name  = asset?.name || 'Protein'
    const meta  = asset?.metadata ?? {}
    const atomCount = asset?.atoms?.length ?? 0
    const resCount  = meta.residue_count ?? 0
    const chains    = (meta.chain_ids ?? []).join(', ') || '—'

    // Anchor target — free / overhang / assembly part instance.
    const kind = att.target?.kind ?? 'free'
    const anchor = kind === 'overhang'
      ? `overhang <span class="prop-val mono" style="font-size:var(--text-xs)">${att.target.overhang_id}</span> (${att.target.attach_end})`
      : kind === 'assembly'
        ? `part instance <span class="prop-val mono" style="font-size:var(--text-xs)">${att.target.instance_id}</span>`
        : 'free (PDB coordinates)'

    const handleNote = att.handle_complement_bp || att.handle_spacer_nt
      ? `<div class="prop-row">
          <span class="prop-label">handle</span>
          <span class="prop-val">${att.handle_complement_bp} bp duplex${att.handle_spacer_nt ? ` · ${att.handle_spacer_nt} nt spacer` : ''}</span>
        </div>`
      : ''

    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">protein</span>
        <span class="prop-val">${name}</span>
        ${att.visible === false ? '<span class="tag tag-warn">hidden</span>' : ''}
      </div>
      ${asset?.source_filename ? `
      <div class="prop-row">
        <span class="prop-label">source</span>
        <span class="prop-val mono" style="font-size:var(--text-xs)">${asset.source_filename}</span>
      </div>` : ''}
      <div class="prop-row">
        <span class="prop-label">anchor</span>
        <span class="prop-val">${anchor}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">atoms</span>
        <span class="prop-val">${atomCount}</span>
        <span class="prop-label" style="margin-left:8px">residues</span>
        <span class="prop-val">${resCount}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">chains</span>
        <span class="prop-val">${chains}</span>
      </div>
      ${att.conjugation_atom_serial != null ? `
      <div class="prop-row">
        <span class="prop-label">conj atom</span>
        <span class="prop-val">serial ${att.conjugation_atom_serial}</span>
      </div>` : ''}
      ${handleNote}
      <div class="prop-row" style="margin-top:4px">
        <span class="prop-label">attach id</span>
        <span class="prop-val mono" style="font-size:var(--text-xs)">${att.id}</span>
      </div>
      <div class="prop-row" style="margin-top:6px">
        <button id="protein-validate-btn" type="button">Validate conjugate</button>
        <span id="protein-validation-status" class="dim" style="margin-left:7px"></span>
      </div>
    `
    const validateBtn = content.querySelector('#protein-validate-btn')
    const validationStatus = content.querySelector('#protein-validation-status')
    validateBtn?.addEventListener('click', async () => {
      validateBtn.disabled = true
      validationStatus.textContent = 'Validating…'
      try {
        const report = await api.getProteinValidation()
        const element = report?.elements?.find(item => item.attachment_id === att.id)
        const related = report?.findings?.filter(item =>
          item.asset_id === att.asset_id
          || item.free_attachment_ids?.includes(att.id)
          || item.conjugated_attachment_ids?.includes(att.id)) ?? []
        const failures = [...(element?.failed_metrics ?? []), ...related.map(item => item.code)]
        validationStatus.textContent = failures.length
          ? `Failed: ${failures.join(', ')}`
          : `Valid · ${Number(report?.audit_ms ?? 0).toFixed(1)} ms`
        validationStatus.classList.toggle('tag-warn', failures.length > 0)
        const repair = related.find(item => item.code === 'legacy_unconverted_free_placement'
          && item.repairable
          && item.free_attachment_ids?.length === 1
          && item.conjugated_attachment_ids?.length === 1)
        content.querySelector('#protein-repair-duplicate-btn')?.remove()
        if (repair) {
          const repairBtn = document.createElement('button')
          repairBtn.id = 'protein-repair-duplicate-btn'
          repairBtn.type = 'button'
          repairBtn.textContent = 'Repair duplicate'
          repairBtn.style.marginLeft = '7px'
          validationStatus.insertAdjacentElement('afterend', repairBtn)
          repairBtn.addEventListener('click', async () => {
            repairBtn.disabled = true
            try {
              const args = {
                freeAttachmentId: repair.free_attachment_ids[0],
                conjugatedAttachmentId: repair.conjugated_attachment_ids[0],
              }
              await api.repairProteinDuplicate(args) // server-side proof, read-only preview
              if (!globalThis.confirm?.('Remove the superseded free protein placement? This is undoable.')) return
              await api.repairProteinDuplicate({ ...args, apply: true })
            } catch (error) {
              validationStatus.textContent = `Repair failed: ${error?.message ?? error}`
              validationStatus.classList.add('tag-warn')
            } finally {
              repairBtn.disabled = false
            }
          })
        }
      } catch (error) {
        validationStatus.textContent = `Validation failed: ${error?.message ?? error}`
        validationStatus.classList.add('tag-warn')
      } finally {
        validateBtn.disabled = false
      }
    })
  }

  /** Canonical Base-ref readout. Keys are app-wide identities from base_ref.js. */
  function _renderBaseKeys(keys) {
    const state = store.getState()
    const rows = selectedBaseDisplayRows(keys, state.currentDesign, state.currentGeometry)
    if (keys.length === 1) {
      const parsed = parseBaseKey(keys[0])
      const geometry = state.currentGeometry ?? []
      const nuc = geometry.find(n => n.helix_id === parsed?.helix_id
        && n.bp_index === parsed?.bp_index
        && String(n.direction).toUpperCase() === String(parsed?.direction).toUpperCase()
        && Number(n.copy_k ?? n.copy ?? 0) === Number(parsed?.copy ?? 0))
      const strand = state.currentDesign?.strands?.find(s => s.id === nuc?.strand_id)
      const domainIndex = strand?.domains?.findIndex(d => d.helix_id === parsed?.helix_id
        && String(d.direction).toUpperCase() === String(parsed?.direction).toUpperCase()
        && parsed.bp_index >= Math.min(d.start_bp, d.end_bp)
        && parsed.bp_index <= Math.max(d.start_bp, d.end_bp)) ?? -1
      let position = null
      if (strand && domainIndex >= 0) {
        const helixById = new Map((state.currentDesign?.helices ?? []).map(h => [h.id, h]))
        position = 1
        for (let i = 0; i < domainIndex; i++) {
          const d = strand.domains[i]
          const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
          const delta = helixById.get(d.helix_id)?.loop_skips
            ?.filter(ls => ls.bp_index >= lo && ls.bp_index <= hi)
            .reduce((sum, ls) => sum + ls.delta, 0) ?? 0
          position += Math.abs(d.end_bp - d.start_bp) + 1 + delta
        }
        const d = strand.domains[domainIndex]
        const step = d.end_bp >= d.start_bp ? 1 : -1
        position += Math.abs(parsed.bp_index - d.start_bp)
        const beforeDelta = helixById.get(d.helix_id)?.loop_skips
          ?.filter(ls => (ls.bp_index - d.start_bp) * step >= 0
            && (ls.bp_index - parsed.bp_index) * step < 0)
          .reduce((sum, ls) => sum + ls.delta, 0) ?? 0
        position += beforeDelta + Number(parsed.copy ?? 0)
      }
      const sequenceBase = position && strand?.sequence?.[position - 1]
      const base = String(nuc?.nucleobase ?? sequenceBase ?? 'N').toUpperCase()
      const location = rows[0]?.label ?? 'Base - ?[?]'
      const strandType = rows[0]?.type?.toLowerCase() ?? 'strand'
      const strandId = strandDisplayId(strand?.id, state.currentDesign)
      content.innerHTML = `
        <div class="prop-row"><span class="prop-label">base</span><span class="prop-val">${base}</span></div>
        <div class="prop-row"><span class="prop-label">location</span><span class="prop-val">${location}</span></div>
        <div class="prop-row"><span class="prop-label">position</span><span class="prop-val">${position ?? '—'} in ${strandType} ${strandId}</span></div>
      `
      return
    }
    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">bases</span>
        <span class="prop-val">${keys.length}</span>
      </div>
    `
    for (const row of rows) {
      const el = document.createElement('div')
      el.className = 'prop-row'
      const value = document.createElement('span')
      value.className = 'prop-val'
      value.textContent = row.label
      el.appendChild(value)
      content.appendChild(el)
    }
  }

  function _render(displayObject) {
    if (!displayObject) {
      content.innerHTML = '<span class="dim">Click a backbone bead to select.</span>'
      return
    }

    if (displayObject.type === 'strand') {
      _renderStrand(displayObject)
    } else if (displayObject.type === 'domain') {
      _renderDomain(displayObject)
    } else if (displayObject.type === 'overhang') {
      _renderOverhang(displayObject)
    } else if (displayObject.type === 'extension') {
      _renderExtension(displayObject)
    } else if (displayObject.type === 'nucleotide') {
      _renderNucleotide(displayObject)
    } else if (displayObject.type === 'bond') {
      _renderBond(displayObject)
    } else if (displayObject.type === 'crossover' || displayObject.type === 'forced_ligation') {
      _renderCrossover(displayObject)
    } else if (displayObject.type === 'cluster') {
      _renderCluster(displayObject)
    } else if (displayObject.type === 'protein') {
      _renderProtein(displayObject)
    } else {
      _renderNucleotide(displayObject)
    }
  }

  function _canonicalDisplay(state) {
    const selection = canonicalSelection(state)
    const baseKeys = selection.items.filter(ref => ref.kind === 'base').map(ref => ref.key)
    if (baseKeys.length) return { baseKeys, displayObject: null }
    const ref = selection.primary
    if (ref?.kind === 'strand') {
      return { baseKeys: [], displayObject: { type: 'strand', id: ref.id, data: { strand_id: ref.id } } }
    }
    if (ref?.kind === 'domain') {
      const domain = state.currentDesign?.strands?.find(s => s.id === ref.strandId)?.domains?.[ref.domainIndex]
      return { baseKeys: [], displayObject: { type: 'domain', id: `${ref.strandId}:${ref.domainIndex}`, data: {
        strand_id: ref.strandId, domain_index: ref.domainIndex,
        helix_id: domain?.helix_id ?? null, direction: domain?.direction ?? null,
        overhang_id: domain?.overhang_id ?? null,
      } } }
    }
    if (ref?.kind === 'overhang') {
      const target = overhangSelectionTarget(state, ref)
      return { baseKeys: [], displayObject: { type: 'overhang', id: ref.id, data: {
        ...(target?.overhang ?? {}), strandId: target?.strandId ?? null,
        domain: target?.domain ?? null, domainIndex: target?.domainIndex ?? null,
      } } }
    }
    if (ref?.kind === 'extension') {
      const target = extensionSelectionTarget(state, ref)
      return { baseKeys: [], displayObject: { type: 'extension', id: ref.id, data: {
        ...(target?.extension ?? {}), strandId: target?.strandId ?? null,
      } } }
    }
    if (ref?.kind === 'cluster') {
      const cluster = state.currentDesign?.cluster_transforms?.find(item => item.id === ref.id)
      return { baseKeys: [], displayObject: { type: 'cluster', id: ref.id, data: cluster ?? { cluster_id: ref.id } } }
    }
    if (ref?.kind === 'bond') {
      return { baseKeys: [], displayObject: { type: 'bond', data: {
        fromKey: ref.fromKey, toKey: ref.toKey,
        strandId: ref.strandId ?? null,
        from: parseBaseKey(ref.fromKey), to: parseBaseKey(ref.toKey),
      } } }
    }
    if (ref?.kind === 'crossover') {
      const collection = ref.subtype === 'forced_ligation'
        ? state.currentDesign?.forced_ligations : state.currentDesign?.crossovers
      const entity = collection?.find(item => item.id === ref.id) ?? { id: ref.id }
      return { baseKeys: [], displayObject: { type: ref.subtype, id: ref.id, data: entity } }
    }
    if (ref?.kind === 'protein') {
      return { baseKeys: [], displayObject: { type: 'protein', id: ref.id, data: { attachment_id: ref.id } } }
    }
    return { baseKeys: [], displayObject: null }
  }

  function _renderState(state) {
    const display = _canonicalDisplay(state)
    if (display.baseKeys.length) _renderBaseKeys(display.baseKeys)
    else _render(display.displayObject)
  }

  // Initial render
  _renderState(store.getState())

  // Subscribe to both selection and design changes (design change updates strand lengths)
  store.subscribe((newState, prevState) => {
    const selChanged = newState.selection !== prevState.selection
    const designChanged = newState.currentDesign !== prevState.currentDesign
    if (selChanged || designChanged) _renderState(newState)
  })
}
