import { appendRasterEvidence, appendTableEvidence } from './article_import_evidence.js'
/** Candidate selection and evidence review; never commits an inferred molecule. */
export function createArticleDesignSelection({ body, fetchImpl, readPayload, onSelectionChange = () => {} }) {
  const host = document.createElement('section')
  host.className = 'article-designs'
  host.innerHTML = `<h3>Detect designs and staple lists</h3>
    <p>Analyze uploaded PDFs and sequence tables. M13mp18 is tested unless you provide a scaffold sequence. Both path directions and sequence-supported registers are tested.</p>
    <button data-analyze>Detect designs</button> <button data-analysis-cancel disabled>Cancel analysis</button>
    <p data-analysis-status role="status"></p><p data-selection-status></p><div data-designs></div>`
  body.append(host)
  const q = s => host.querySelector(s)
  let revision = 0, controller = null
  const selected = new Set()
  const selections = new Map()
  function selectionStatus() { q('[data-selection-status]').textContent = `${selected.size} detected design(s) selected for review.`; onSelectionChange([...selected].map(id => selections.get(id)).filter(Boolean)) }
  function reset() {
    revision++; controller?.abort(); controller = null; selected.clear(); selections.clear(); onSelectionChange([])
    q('[data-designs]').replaceChildren(); q('[data-analysis-status]').textContent = ''
    q('[data-selection-status]').textContent = ''; q('[data-analyze]').disabled = false
    q('[data-analysis-cancel]').disabled = true
  }
  function render(report) {
    for (const design of report.designs) {
      const card = document.createElement('article')
      card.className = 'article-design-card'
      const label = document.createElement('label'), checkbox = document.createElement('input')
      checkbox.type = 'checkbox'; checkbox.dataset.designId = design.id
      checkbox.addEventListener('change', () => { if (checkbox.checked) selected.add(design.id); else selected.delete(design.id); selectionStatus() })
      label.append(checkbox, document.createTextNode(` ${design.label}`)); card.append(label)
      const image = document.createElement('img'); image.src = design.image; image.alt = design.label; card.append(image)
      const context = document.createElement('p'); context.textContent = design.context; card.append(context)
      const summary = document.createElement('p')
      summary.textContent = `${design.rows} image rows · ${design.branches} junction branches · ${design.observed_paths.length} observed paths · ${design.route_hypotheses_tested} calibration hypotheses`
      card.append(summary)
      appendRasterEvidence(card, design.raster_evidence)
      const choices = document.createElement('select'); choices.setAttribute('aria-label', `Staple list for ${design.label}`)
      const none = document.createElement('option'); none.value = ''; none.textContent = 'No staple list selected'; choices.append(none)
      for (const pairing of design.pairings) {
        const option = document.createElement('option'); option.value = pairing.list_id
        option.textContent = `${pairing.label} · ${pairing.list_rows} oligos · ${pairing.basis}`; choices.append(option)
      }
      const evidence = document.createElement('div'); evidence.dataset.pairingEvidence = design.id
      function showPairing() {
        evidence.replaceChildren()
        const pairing = design.pairings.find(p => p.list_id === choices.value)
        selections.delete(design.id)
        if (pairing?.publication_evidence) selections.set(design.id, { source_sha256: design.source_sha256, diagram_page: design.page, table_page: pairing.publication_evidence.table_page })
        if (pairing?.table_import && pairing.table_source_sha256 === design.source_sha256) {
          selections.set(design.id, { source_sha256: design.source_sha256, diagram_page: design.page, table_page: pairing.table_page })
          appendTableEvidence(evidence, pairing.table_import, modules => {
            const choice = selections.get(design.id)
            if (choice) { if (modules.length) choice.table_modules = modules; else delete choice.table_modules }
            selectionStatus()
          })
        }
        selectionStatus()
        if (!pairing) {
          evidence.textContent = design.pairings.length ? 'Select a likely staple list to compare hypotheses.' : 'No sufficiently supported staple-list pairing. Upload a labelled list or improve the diagram evidence.'
          return
        }
        const status = document.createElement('p')
        const sequenceSearch = pairing.publication_evidence?.sequence_search
        status.textContent = sequenceSearch?.status === 'supported_with_length_discrepancy' ? 'Sequence-supported reconstruction candidate with a one-base scaffold length discrepancy; confidence is penalized.' : sequenceSearch?.resolved ? 'One scaffold direction/register matches every supplied staple exactly.' : pairing.publication_evidence ? 'Staple directions are anchored by the published endpoint table; sequence complementarity remains unverified.' : pairing.direction_resolved ? 'One direction/register hypothesis has the strongest sequence support.' : 'Direction or register unresolved; alternatives remain candidates.'
        evidence.append(status)
        if (pairing.publication_evidence) {
          const item = pairing.publication_evidence
          const recovered = document.createElement('p'); recovered.dataset.publicationRouting = ''
          recovered.textContent = `${item.matched_staples}/${item.table_rows} published staple endpoint pairs recovered from the figure; ${item.lengths_agree} path lengths agree. Base-index correction: ${item.base_index_offset}. ${item.scaffold_paths} scaffold path(s) oriented by antiparallel agreement; ${item.unclassified_paths} path(s) remain unclassified. ${item.unit_insertions_resolved ?? 0} unit insertions resolved; ${item.unresolved_insertions ?? 0} insertion lengths unresolved. ${item.limitation}`
          evidence.append(recovered)
          if (item.vector_panel_registration && !item.recovered_topology?.lattice?.resolved) {
            const placement = document.createElement('p')
            placement.textContent = 'Routing was recovered across the panels. Native reconstruction still needs verified lattice placement.'
            evidence.append(placement)
          }
          if (item.staple_overhangs?.bases) {
            const overhang = document.createElement('p'); overhang.dataset.stapleOverhangs = ''
            const o = item.staple_overhangs
            overhang.textContent = `On-helix staple overhangs: ${o.bases} bases; ${o.image_verified_bases} image/table matches, ${o.table_fallback_bases} assigned from the table where image letters are unavailable, ${o.conflicting_bases} image/table conflicts. Table fallback is an explicit assumption, not independent sequence validation.`
            const conflicts = (o.runs ?? []).flatMap(run => run.bases ?? []).filter(base => base.status === 'conflict')
            if (conflicts.length) overhang.textContent += ` Potential conflicts (notices): ${conflicts.map(base => `helix ${base.site[0]}[${base.site[1]}]: image ${base.image_base ?? 'ambiguous'}, table ${base.table_base}; selected ${base.selected_base ?? 'unresolved'}${base.selection_reason === 'preference_tie_break' ? ' (equal evidence; T > A > C > G)' : ''}`).join('; ')}.`
            evidence.append(overhang)
          }
          if (sequenceSearch) {
            const search = document.createElement('p'); search.dataset.sequenceSearch = ''
            search.textContent = sequenceSearch.best
              ? `${sequenceSearch.scaffold_name}: ${sequenceSearch.candidates_tested} direction/shift candidates tested. Best: ${sequenceSearch.best.mismatches} mismatches across ${sequenceSearch.best.compared_bases} paired bases; ${sequenceSearch.best.exact_staples} exact staples; ${sequenceSearch.best_ties} best candidate(s). Offset ${sequenceSearch.best.offset}, direction ${sequenceSearch.best.reverse ? 'reversed' : 'recovered'}. Next-best: ${sequenceSearch.runner_up_mismatches} mismatches. ${sequenceSearch.nick_note} ${sequenceSearch.selection_basis ?? ''}. Unmatched table rows: ${sequenceSearch.unmatched_table_rows ?? 0}; invalid sequence rows: ${sequenceSearch.invalid_staple_rows?.length ?? 0}; bases without scaffold partners: ${sequenceSearch.best.unknown_bases ?? 0}.`
              : sequenceSearch.reason
            evidence.append(search)
            if (sequenceSearch.confidence) {
              const confidence = document.createElement('p'); confidence.dataset.sequenceConfidence = ''
              const c = sequenceSearch.confidence
              confidence.textContent = `Sequence-evidence confidence score: ${c.score}/100. ${c.kind}. ${c.penalties.map(p => `${p.reason}: −${p.points.toFixed(2)} points`).join('; ')}`
              evidence.append(confidence)
            }
            if (sequenceSearch.insertion_hypothesis) {
              const loops = document.createElement('p'); loops.dataset.scaffoldLoops = ''
              loops.textContent = `Scaffold-loop hypothesis: ${sequenceSearch.insertion_hypothesis.counts.map(([h, bp, n]) => `helix ${h}, base ${bp}: ${n} inserted bases`).join('; ')}. ${sequenceSearch.insertion_hypothesis.sequence_supported ? 'Supported by flanking sequence evidence.' : 'Unresolved sequence hypothesis.'}`
              evidence.append(loops)
            }
            if (sequenceSearch.length_discrepancy) {
              const discrepancy = document.createElement('p'); discrepancy.dataset.lengthDiscrepancy = ''
              discrepancy.textContent = `Represented scaffold: ${sequenceSearch.represented_length} bases; sequence: ${sequenceSearch.scaffold_length} bases. ${sequenceSearch.length_discrepancy_note} A publication/design error is a possible explanation, not an established cause.`
              evidence.append(discrepancy)
            }
          }
        }
        if (pairing.routing_recovered) {
          const recovered = document.createElement('p'); recovered.dataset.routingRecovered = ''
          const routing = pairing.routing
          recovered.textContent = `Directed routing recovered: ${routing.directed_paths.scaf.length} scaffold(s), ${routing.directed_paths.stap.length} staples, ${routing.deletions.length} deletion annotation(s). Directions are resolved independently per staple. This is image-derived topology; molecular geometry has not been built.`
          evidence.append(recovered)
        }
        for (const h of pairing.alternatives) {
          const detail = document.createElement('details'), title = document.createElement('summary'), text = document.createElement('p')
          title.textContent = `${h.matched_staples}/${h.list_rows} staples matched · scaffold ${h.scaffold_direction}, staples ${h.staple_direction} · offset ${h.scaffold_offset} · evidence score ${h.evidence_score}%`
          text.textContent = `${h.paired_bases_verified} paired bases agree; ${h.unknown_bases} bases have unknown partners. ${h.calibration.method}, ${h.calibration.points_per_base.toFixed(4)} PDF points/base. This score is not a reconstruction probability.`
          detail.append(title, text); evidence.append(detail)
        }
        if (!pairing.alternatives.length && !pairing.publication_evidence) evidence.append(document.createTextNode('Pairing is based on shared caption/list labels only; no sequence-supported route recovered.'))
      }
      choices.addEventListener('change', showPairing); showPairing(); card.append(choices, evidence)
      const limits = document.createElement('p'); limits.textContent = design.limitations.join(' '); card.append(limits)
      q('[data-designs]').append(card)
    }
    selectionStatus()
    q('[data-analysis-status]').textContent = `${report.designs.length} candidate design(s), ${report.staple_lists.length} staple list(s) detected. ${report.notes.join(' ')}`
  }
  q('[data-analyze]').addEventListener('click', async () => {
    reset(); const current = revision; controller = new AbortController(); const signal = controller.signal
    q('[data-analyze]').disabled = true; q('[data-analysis-cancel]').disabled = false
    q('[data-analysis-status]').textContent = 'Detecting figures, extracting staple lists and testing route hypotheses…'
    try {
      const payload = await readPayload()
      if (current !== revision) return
      const response = await fetchImpl('/api/article-reconstruction/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal })
      const result = await response.json()
      if (current !== revision) return
      if (!response.ok) throw new Error(result.detail || 'Design detection failed.')
      render(result)
    } catch (error) {
      if (current === revision) q('[data-analysis-status]').textContent = error.name === 'AbortError' ? 'Analysis canceled.' : error.message
    } finally {
      if (current === revision) { q('[data-analyze]').disabled = false; q('[data-analysis-cancel]').disabled = true }
    }
  })
  q('[data-analysis-cancel]').addEventListener('click', () => { reset(); q('[data-analysis-status]').textContent = 'Analysis canceled.' })
  return { reset, dispose: reset, selectedDesigns: () => [...selected], selectedReconstructions: () => [...selected].map(id => selections.get(id)).filter(Boolean) }
}
