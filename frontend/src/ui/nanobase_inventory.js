/** Evidence inventory only: opening it never imports a design or starts a simulation. */
import { createModal } from './primitives/modal.js'
import inventory from '../data/nanobase_inventory.json'
import './nanobase_inventory.css'

let active = null
export function safeExternalURL(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null } catch { return null }
}
export function filterInventory(records, { query = '', software = '', publication = '', figures = '' } = {}) {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean)
  return records.filter(row => {
    const text = JSON.stringify(row).toLowerCase()
    return terms.every(term => text.includes(term)) && (!software || row.software.includes(software)) &&
      (!publication || (publication === 'none' ? row.publication.status === 'No publication supplied' :
        publication === 'journal' ? row.publication.status.startsWith('Journal') : row.publication.status.startsWith('Preprint'))) &&
      (!figures || (figures === 'verified' ? row.supplement.status.startsWith('Verified') : !row.supplement.status.startsWith('Verified')))
  })
}
export function inventoryCSV(records) {
  const rows = [['Nanobase ID', 'Design', 'Software', 'Files (category: name)', 'Publication status', 'Publication', 'Publication URL', 'Supplement figure status', 'Supplement evidence', 'Design/publication comparison', 'Notes', 'Nanobase URL'],
    ...records.map(r => [r.id, r.title, r.software.join('; '), r.files.map(f => `${f.category}: ${f.name}`).join('; '), r.publication.status, r.publication.title || '', r.publication.url || '', r.supplement.status, r.supplement.evidence.map(e => `${e.label}: ${e.url}`).join('; '), r.comparison, r.notes.join('; '), r.source_url])]
  return rows.map(row => row.map(v => { let s = String(v ?? ''); if (/^[\s]*[=+@-]/.test(s)) s = "'" + s; return `"${s.replaceAll('"', '""')}"` }).join(',')).join('\r\n')
}
export function showNanobaseInventory({ snapshot = inventory } = {}) {
  if (active?.isOpen()) return active
  const body = document.createElement('div'); body.className = 'nanobase-inventory'
  body.innerHTML = `<p data-provenance></p>
    <p>Publication links establish provenance, not equivalence. Uploaded files may be reconstructions or modified variants. Simulation files do not establish equilibration or validation. A supplementary routing figure is not automatically a matched training pair.</p>
    <div class="ni-controls"><label>Search <input type="search" data-search placeholder="Design, DOI, file, discrepancy…"></label>
    <label>Software <select data-software><option value="">All software</option></select></label>
    <label>Publication <select data-publication><option value="">All records</option><option value="journal">Journal linked</option><option value="preprint">Preprint linked</option><option value="none">None supplied</option></select></label>
    <label>Figures <select data-figures><option value="">All evidence states</option><option value="verified">Verified routing figure</option><option value="unresolved">Not visually verified</option></select></label>
    <button data-csv>Export filtered CSV</button><button data-json>Export evidence JSON</button></div>
    <p data-count role="status" aria-live="polite"></p>
    <div class="ni-scroll" tabindex="0" aria-label="Nanobase inventory table"><table><caption>Public Nanobase designs and publication evidence</caption><thead><tr><th scope="col">Design / source</th><th scope="col">File type / software</th><th scope="col">Simulation / coordinate files</th><th scope="col">Publication</th><th scope="col">Supplementary design figures</th><th scope="col">Correspondence / review notes</th></tr></thead><tbody></tbody></table></div>`
  const q = selector => body.querySelector(selector)
  q('[data-provenance]').textContent = `Snapshot: ${snapshot.retrieved_at}. ${snapshot.coverage}. Public metadata and file manifests; native JSON schemas inspected where retrievable.`
  for (const software of [...new Set(snapshot.records.flatMap(r => r.software))].sort()) {
    const option = document.createElement('option'); option.value = software; option.textContent = software; q('[data-software]').append(option)
  }
  const addText = (parent, text, tag = 'p') => { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node }
  function link(parent, label, url) {
    const href = safeExternalURL(url)
    const node = addText(parent, label, href ? 'a' : 'span')
    if (href) { node.href = href; node.target = '_blank'; node.rel = 'noopener noreferrer' }
    return node
  }
  function fileList(parent, files) {
    if (!files.length) { addText(parent, 'None listed'); return }
    const details = document.createElement('details'); addText(details, `${files.length} file${files.length === 1 ? '' : 's'} · ${[...new Set(files.map(f => f.name.split('.').pop().toLowerCase()))].join(', ')}`, 'summary')
    for (const f of files) { const p = addText(details, '', 'p'); link(p, f.name, f.url); if (f.schema) addText(p, ` · ${f.schema}`, 'span') }
    parent.append(details)
  }
  let visible = []
  function render() {
    visible = filterInventory(snapshot.records, { query: q('[data-search]').value, software: q('[data-software]').value, publication: q('[data-publication]').value, figures: q('[data-figures]').value })
    q('[data-count]').textContent = `${visible.length} of ${snapshot.records.length} records · ${visible.filter(r => r.supplement.status.startsWith('Verified')).length} with visually verified publication routing figures · uploaded-file equivalence requires separate review`
    const tbody = q('tbody'); tbody.replaceChildren()
    for (const row of visible) {
      const tr = document.createElement('tr'); const cells = Array.from({ length: 6 }, () => { const td = document.createElement('td'); tr.append(td); return td })
      link(cells[0], row.title, row.source_url); addText(cells[0], `Nanobase ${row.id}`)
      addText(cells[1], row.software.join(' · ')); fileList(cells[1], row.files.filter(f => f.category !== 'simulation'))
      fileList(cells[2], row.files.filter(f => f.category === 'simulation'))
      addText(cells[3], row.publication.status); if (row.publication.title || row.publication.url) link(cells[3], row.publication.title || row.publication.url, row.publication.url)
      if (row.publication.note) addText(cells[3], row.publication.note)
      addText(cells[4], row.supplement.status); for (const e of row.supplement.evidence) { const p = addText(cells[4], ''); link(p, e.label, e.url) }
      if (row.supplement.note) addText(cells[4], row.supplement.note)
      addText(cells[5], row.comparison); for (const note of row.notes) addText(cells[5], note)
      tbody.append(tr)
    }
    if (!visible.length) { const tr = document.createElement('tr'); const td = addText(tr, 'No matching records.', 'td'); td.colSpan = 6; tbody.append(tr) }
  }
  for (const selector of ['[data-search]', '[data-software]', '[data-publication]', '[data-figures]']) q(selector).addEventListener(selector === '[data-search]' ? 'input' : 'change', render)
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  q('[data-csv]').addEventListener('click', () => download('nanobase-inventory.csv', inventoryCSV(visible), 'text/csv;charset=utf-8'))
  q('[data-json]').addEventListener('click', () => download('nanobase-evidence.json', JSON.stringify({ ...snapshot, records: visible, export_scope: 'Current filters' }, null, 2), 'application/json'))
  const modal = createModal({ title: 'Nanobase publication inventory', body, size: 'xl', className: 'ni-modal', onClose: () => { active = null; body.replaceChildren() } })
  active = modal; render(); modal.open(); return modal
}
