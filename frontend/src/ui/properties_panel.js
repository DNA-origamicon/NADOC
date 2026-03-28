/**
 * Properties panel — shows selected object details in the right panel.
 *
 * Subscribes to store.selectedObject and renders into #properties-content.
 *
 * Four display modes:
 *   strand     — per-strand summary (length nt, domains, helix coverage)
 *   domain     — per-domain detail (helix, range, direction, overhang flag)
 *   nucleotide — per-bead detail (helix, bp, backbone/base positions)
 *   cone       — connector between two nucleotides
 */

import { store } from '../state/store.js'
import * as api from '../api/client.js'

export function initPropertiesPanel() {
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

  function _renderStrand(selectedObject) {
    const design = store.getState().currentDesign
    const strandId = selectedObject.data?.strand_id
    if (!design || !strandId) {
      content.innerHTML = `<span class="dim">Strand selected.</span>`
      return
    }

    const strand = design.strands.find(s => s.id === strandId)
    if (!strand) {
      content.innerHTML = `<span class="dim">Strand not found in design.</span>`
      return
    }

    const lengthNt = _strandLength(strand, design)
    const domainCount = strand.domains.length
    const helixIds = [...new Set(strand.domains.map(d => d.helix_id))]

    // Canonical range indicator
    const rangeClass = lengthNt < 18 ? 'tag-warn' : lengthNt > 50 ? 'tag-warn' : 'tag-ok'
    const rangeLabel = lengthNt < 18
      ? `<span class="tag ${rangeClass}">short (${lengthNt} nt)</span>`
      : lengthNt > 50
        ? `<span class="tag ${rangeClass}">long (${lengthNt} nt)</span>`
        : `<span class="tag ${rangeClass}">${lengthNt} nt</span>`

    const typeTag = strand.strand_type === 'scaffold'
      ? '<span class="tag tag-scaffold">scaffold</span>'
      : '<span class="tag tag-staple">staple</span>'

    const domainRows = strand.domains.map((d, i) => {
      const len = Math.abs(d.end_bp - d.start_bp) + 1
      return `<div class="prop-row" style="padding-left:8px">
        <span class="prop-label" style="min-width:18px">${i}</span>
        <span class="prop-val mono">${d.helix_id} · ${d.start_bp}→${d.end_bp} (${len} bp) ${d.direction}</span>
      </div>`
    }).join('')

    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">strand</span>
        <span class="prop-val">${strandId}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">type</span>
        ${typeTag} ${rangeLabel}
      </div>
      <div class="prop-row">
        <span class="prop-label">length</span>
        <span class="prop-val">${lengthNt} nt</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">domains</span>
        <span class="prop-val">${domainCount}</span>
      </div>
      <div class="prop-row">
        <span class="prop-label">helices</span>
        <span class="prop-val">${helixIds.join(', ')}</span>
      </div>
      <div style="margin-top:6px; border-top:1px solid #21262d; padding-top:4px">
        <div class="prop-row" style="margin-bottom:3px">
          <span class="prop-label">domains</span>
        </div>
        ${domainRows}
      </div>
    `
  }

  function _renderNucleotide(selectedObject) {
    const nuc = selectedObject.data
    const design = store.getState().currentDesign
    const helix  = design?.helices?.find(h => h.id === nuc.helix_id)

    const scaffoldTag = nuc.strand_type === 'scaffold'
      ? '<span class="tag tag-scaffold">scaffold</span>'
      : '<span class="tag tag-staple">staple</span>'

    const endTag = nuc.is_five_prime
      ? "<span class=\"tag tag-end\">5′ end</span>"
      : nuc.is_three_prime
        ? "<span class=\"tag tag-end\">3′ end</span>"
        : ''

    content.innerHTML = `
      <div class="prop-row">
        <span class="prop-label">helix</span>
        <span class="prop-val">${nuc.helix_id}</span>
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
          store.setState({ selectedObject: null })
        }
      })
    }
  }

  function _renderDomain(selectedObject) {
    const design = store.getState().currentDesign
    const { strand_id, domain_index, helix_id, direction, overhang_id } = selectedObject.data ?? {}
    const strand = design?.strands?.find(s => s.id === strand_id)
    const domain = strand?.domains?.[domain_index]

    if (!domain) {
      content.innerHTML = `<span class="dim">Domain selected.</span>`
      return
    }

    const len = Math.abs(domain.end_bp - domain.start_bp) + 1
    const typeTag = strand.strand_type === 'scaffold'
      ? '<span class="tag tag-scaffold">scaffold</span>'
      : '<span class="tag tag-staple">staple</span>'
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
        <span class="prop-val">${helix_id}</span>
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
        <span class="prop-val mono" style="font-size:9px">${overhang_id}</span>
      </div>` : ''}
      <div class="prop-row" style="margin-top:4px">
        <span class="prop-label">strand</span>
        <span class="prop-val mono" style="font-size:9px">${strand_id}</span>
      </div>
    `
  }

  function _render(selectedObject) {
    if (!selectedObject) {
      content.innerHTML = '<span class="dim">Click a backbone bead to select.</span>'
      return
    }

    if (selectedObject.type === 'strand') {
      _renderStrand(selectedObject)
    } else if (selectedObject.type === 'domain') {
      _renderDomain(selectedObject)
    } else if (selectedObject.type === 'nucleotide') {
      _renderNucleotide(selectedObject)
    } else if (selectedObject.type === 'cone') {
      // Cone selected — show strand info for the strand it belongs to
      _renderStrand({
        type: 'strand',
        data: { strand_id: selectedObject.data?.strand_id },
      })
    } else {
      _renderNucleotide(selectedObject)
    }
  }

  // Initial render
  _render(store.getState().selectedObject)

  // Subscribe to both selection and design changes (design change updates strand lengths)
  store.subscribe((newState, prevState) => {
    const selChanged = newState.selectedObject !== prevState.selectedObject
    const designChanged = newState.currentDesign !== prevState.currentDesign
    if (selChanged || (designChanged && newState.selectedObject)) {
      _render(newState.selectedObject)
    }
  })
}
