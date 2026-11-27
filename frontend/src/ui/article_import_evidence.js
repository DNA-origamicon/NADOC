/** Render source observations without presenting pixel traces as nucleotide routes. */
export function appendRasterEvidence(card, raster) {
  if (!raster) return
  const details = document.createElement('details'), summary = document.createElement('summary')
  summary.textContent = `${raster.path_count} raster color traces · base registration unresolved`
  const text = document.createElement('p')
  text.textContent = `${raster.placements.length} image placements composited in PDF order. ${raster.unresolved.join(' ')}${raster.truncated ? ' Trace limit reached; evidence is incomplete.' : ''}`
  const registrations = raster.panel_registration?.comparisons ?? []
  const supported = registrations.filter(c => c.status === 'supported_image_overlap')
  if (registrations.length) text.textContent += ` ${supported.length} supported panel overlap(s) from grid-normalized correlation; this aligns images without assigning molecular connections.`
  const panels = raster.classified_tracing?.panels ?? []
  if (panels.length) {
    const supported = panels.filter(p => p.lane_classification.status === 'panel_pattern_supported').length
    const traces = panels.flatMap(p => p.traces ?? [])
    const staples = traces.filter(t => t.kind === 'staple').length
    const unbranched = traces.filter(t => t.status === 'unbranched_staple_trace').length
    const connectors = raster.classified_tracing.connector_drawing_count ?? 0
    const candidates = raster.classified_tracing.connector_candidate_count ?? 0
    const markers = raster.classified_tracing.offset_marker_count ?? 0
    text.textContent += ` ${connectors} same-helix connector drawing(s), ${candidates} unresolved connector hypothesis/hypotheses, ${markers} offset endpoint-marker observation(s). Connector drawing lengths are excluded from base counts.`
    text.textContent += ` ${supported}/${panels.length} panel placements support scaffold/staple lane classification. ${staples} classified staple traces (${unbranched} unbranched); these may be fragments, not complete strands. Unclassified and scaffold strokes are excluded from staple matching.`
  }
  details.append(summary, text); card.append(details)
}

export function appendTableEvidence(host, table, onChange) {
  if (!table) return
  const summary = document.createElement('p')
  summary.textContent = `${table.rows.length} physical sequence rows on pages ${table.pages.join(', ')}. ${table.notices.join(' ')}`
  const select = document.createElement('select'); select.multiple = true
  select.setAttribute('aria-label', 'Table modules to include in reconstruction report')
  for (const [name, count] of Object.entries(table.module_counts)) {
    const option = document.createElement('option'); option.value = name; option.textContent = `${name}: ${count}`; select.append(option)
  }
  const hint = document.createElement('p'); hint.textContent = 'Select modules for the report (Ctrl/Cmd-click for multiple). With no selection, all rows remain unassigned evidence; alternatives are not combined into a design.'
  select.addEventListener('change', () => onChange([...select.selectedOptions].map(o => o.value)))
  const notices = document.createElement('ul')
  const counts = new Map()
  for (const row of table.rows) {
    for (const item of row.modifications) {
      const key = `${item.name}: ${item.status.replaceAll('_', ' ')}`
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    for (const item of row.overhang_annotations) {
      const key = `${item.label}: labeled native overhang pending route and unpaired interval`
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
  }
  for (const [text, count] of counts) { const li = document.createElement('li'); li.textContent = `${text} (${count} rows)`; notices.append(li) }
  host.append(summary, hint, select, notices)
}
