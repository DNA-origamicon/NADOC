import { docHeaders } from '../shared/doc_id.js'

/** Projection is a user-calibrated hypothesis, independent of sequence identity. */
export function projectMatch(match, columns, indices, rows, rowMap) {
  if (columns.length < 2 || indices.length !== columns.length || indices.some((v, i) => !Number.isFinite(v) || (i && v <= indices[i - 1]))) return null
  const row = rowMap.indexOf(match.helix_id)
  if (row < 0 || row >= rows.length) return null
  const lo = Math.max(Math.min(match.start_bp, match.end_bp), indices[0])
  const hi = Math.min(Math.max(match.start_bp, match.end_bp), indices.at(-1))
  if (lo > hi) return null
  function x(bp) {
    const j = Math.max(0, indices.findIndex((v, i) => i < indices.length - 1 && bp <= indices[i + 1]))
    return columns[j] + (bp - indices[j]) / (indices[j + 1] - indices[j]) * (columns[j + 1] - columns[j])
  }
  return { x1: x(lo), x2: x(hi), y: rows[row], row, clipped: lo !== Math.min(match.start_bp, match.end_bp) || hi !== Math.max(match.start_bp, match.end_bp) }
}

export const brickControls = `
  <div class="ie-toolbar">
    <label><input data-brick-toggle type="checkbox"> Highlight published sequence matches</label>
    <label>Reference <select data-sequence-reference>
      <option value="42hb13">42hb (1)-(3) · Fig. S1</option><option value="42hb14">42hb (1)-(4) · Fig. S5</option><option value="brick">Brick</option>
    </select></label>
    <label>Sequence preview <select data-sequence-register>
      <option value="current">Current design</option><option value="17">p7560 offset 17 · local candidate</option><option value="0">p7560 offset 0</option><option value="3541">p7560 offset 3541 · superseded local hypothesis</option>
    </select></label>
    <label><input data-reconstruction-toggle type="checkbox"> Fig. S1 proposed nick / junction positions</label>
    <label>Minimum exact match <input data-brick-min type="number" min="6" max="40" step="1" value="12"> bases</label>
    <button data-brick-refresh>Refresh from active design</button>
  </div>
  <p data-brick-status role="status">Uses current sequences in the active design; PDF images contain no nucleotide sequences.</p>
  <details data-brick-mapping-box hidden><summary>Sequence overlay row mapping</summary>
    <p>Rows initially follow design helix order only when row counts agree. This is an editable assumption, not a recovered mapping. Adjust BP column calibration above to align the overlay.</p>
    <div data-brick-mapping></div>
  </details>`

export function createBrickOverlay({ body, fetchImpl, redraw, getFigure, getIndices }) {
  const q = s => body.querySelector(s)
  let result = null, mapping = [], controller = null, revision = 0, loading = false, error = ''
  function mappingControls() {
    const figure = getFigure(), host = q('[data-brick-mapping]'); host.replaceChildren()
    q('[data-brick-mapping-box]').hidden = !result || !figure
    if (!result || !figure) return
    figure.rows.forEach((_, i) => {
      const label = document.createElement('label'); label.textContent = `Image row ${i} `
      const select = document.createElement('select'); select.setAttribute('aria-label', `Sequence helix for image row ${i}`)
      for (const h of [{ id: '', label: 'Unmapped' }, ...result.helices]) {
        const option = document.createElement('option'); option.value = h.id; option.textContent = h.label; select.append(option)
      }
      select.value = mapping[i] || ''
      select.addEventListener('change', () => {
        // One helix can occupy only one inferred image row.
        mapping = mapping.map((h, j) => j !== i && h === select.value ? '' : h)
        mapping[i] = select.value; mappingControls(); redraw()
      })
      label.append(select); host.append(label)
    })
  }
  function selectFigure() {
    const figure = getFigure()
    mapping = figure?.rows.map((_, i) => result?.helices.length === figure.rows.length ? result.helices[i].id : '') || []
    mappingControls()
  }
  async function refresh() {
    controller?.abort(); const current = ++revision; controller = new AbortController()
    const previous = result, previousMapping = [...mapping], previousFigure = getFigure()
    result = null; error = ''; loading = true; selectFigure(); redraw()
    q('[data-brick-status]').textContent = 'Comparing domains with the selected published list…'
    try {
      const minimum = Number(q('[data-brick-min]').value)
      if (!Number.isInteger(minimum) || minimum < 6 || minimum > 40) throw new Error('Minimum match length must be an integer from 6 to 40.')
      const reference = q('[data-sequence-reference]').value
      const register = q('[data-sequence-register]').value
      const params = new URLSearchParams({ minimum: String(minimum), reference })
      if (register !== 'current') params.set('register', register)
      const response = await fetchImpl(`/api/image-evaluation/brick-matches?${params}`, { headers: docHeaders(), signal: controller.signal })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Sequence comparison failed.')
      if (current !== revision) return
      result = data; selectFigure()
      if (previous && previous.design_id === data.design_id && previousFigure === getFigure()) {
        mapping = previousMapping.map(h => data.helices.some(item => item.id === h) ? h : '')
        mappingControls()
      }
    } catch (e) { if (current === revision) error = e.name === 'AbortError' ? 'Comparison canceled.' : e.message }
    finally {
      if (current === revision) { loading = false; status(0, 0); redraw() }
    }
  }
  function status(visible, groups) {
    if (loading) return
    if (error) { q('[data-brick-status]').textContent = error; return }
    if (!result) return
    const domains = new Set(result.matches.map(m => `${m.strand_id}/${m.domain_index}`)).size
    q('[data-brick-status]').textContent = `${result.preview?.notice || ""} ${result.reference.title} · snapshot: ${result.design_name} · ${domains}/${result.domains_checked} domains have exact matches ≥${result.minimum} bases. ${visible}/${groups} matching spans visible. ${q('[data-reconstruction-toggle]').checked ? reconstructionNotice() : ""} Green: whole domain; purple: part of a domain. ${result.skipped_strands.length} strands skipped (missing/inconsistent sequences). Spatial placement uses assumed row mapping and BP calibration; short matches can occur by chance. Refresh after design edits.`
  }
  function reconstructionNotice() {
    return getFigure()?.rows.length === 42 && q('[data-sequence-reference]').value === '42hb13'
      ? 'Orange: proposed nick positions on helices 40 and 41. Dashed bands: alternative scaffold junctions on helix 40. J21/B7220, J22/B539 and J22/B7220 remain unresolved (B is the p7560 branch offset). These markers do not change the BP calibration or design.'
      : 'Reconstruction markers require the 42-row Fig. S1 diagram and the 42hb (1)-(3) list.'
  }
  function drawReconstruction(mark) {
    const figure = getFigure()
    if (!q('[data-reconstruction-toggle]').checked || figure?.rows.length !== 42 || q('[data-sequence-reference]').value !== '42hb13') return
    const items = [
      { label: '41', bp: 37.5, text: 'Helix 41: proposed nick 37/38 (previously 31/32); published staple #46.' },
      { label: '40', bp: 30.5, text: 'Helix 40: proposed nick 30/31 (previously 28/29); published staple #46.' },
      { label: '40', bp: 21.5, alternative: true, text: 'Helix 40: scaffold junction alternative 21/22, p7560 branch offset B7220. Unresolved.' },
      { label: '40', bp: 22.5, alternative: true, text: 'Helix 40: scaffold junction alternative 22/23, p7560 branch offset B539 or B7220. Unresolved.' },
    ]
    for (const item of items) {
      const helix = result.helices.find(h => String(h.label) === item.label)
      if (!helix) continue
      const p = projectMatch({ helix_id: helix.id, start_bp: item.bp, end_bp: item.bp }, figure.columns, getIndices(), figure.rows, mapping)
      if (!p) continue
      mark('rect', { x: p.x1 - 2, y: p.y - 9, width: 4, height: 18, fill: item.alternative ? 'none' : '#e68a00', stroke: '#b65b00', 'stroke-dasharray': item.alternative ? '2 2' : 'none', 'data-reconstruction-position': `${item.label}:${item.bp}` }, item.text, `reconstruction:${item.label}:${item.bp}`)
    }
  }
  function draw(mark) {
    const figure = getFigure()
    if (!result || !figure) { status(0, 0); return }
    drawReconstruction(mark)
    if (!q('[data-brick-toggle]').checked) { status(0, 0); return }
    const groups = new Map()
    for (const m of result.matches) {
      const key = `${m.strand_id}/${m.domain_index}/${m.offset}/${m.length}`
      if (!groups.has(key)) groups.set(key, { match: m, hits: [] })
      groups.get(key).hits.push(`${result.reference.sheet || "Brick"} ${m.published_index} (base ${m.published_offset + 1})`)
    }
    let visible = 0
    for (const [key, { match: m, hits }] of groups) {
      const p = projectMatch(m, figure.columns, getIndices(), figure.rows, mapping)
      if (!p) continue
      visible++
      const detail = `${m.full_domain ? 'Whole domain' : 'Partial domain'}: ${m.length} exact bases, 5′–${m.sequence}–3′. ${m.strand_name}, domain ${m.domain_index + 1}, helix ${result.helices.find(h => h.id === m.helix_id)?.label ?? "unknown"} BP ${m.start_bp}→${m.end_bp}; ${hits.join('; ')}. Same sequence orientation; not proof of correct routing.${p.clipped ? ' Highlight clipped to calibrated columns.' : ''}`
      mark('rect', { x: p.x1 - 1, y: p.y - 3, width: Math.max(3, p.x2 - p.x1 + 2), height: 6, rx: 1, fill: m.full_domain ? '#168044' : '#9c36d0', opacity: .8, 'data-brick-match': key }, detail, `brick:${key}`)
    }
    status(visible, groups.size)
  }
  q('[data-brick-toggle]').addEventListener('change', () => {
    if (q('[data-brick-toggle]').checked && !result) refresh()
    else redraw()
  })
  for (const selector of ['[data-sequence-reference]', '[data-sequence-register]']) {
    q(selector).addEventListener('change', () => { q('[data-brick-toggle]').checked = true; refresh() })
  }
  q('[data-reconstruction-toggle]').addEventListener('change', () => { if (!result) refresh(); else redraw() })
  q('[data-brick-refresh]').addEventListener('click', () => { q('[data-brick-toggle]').checked = true; refresh() })
  q('[data-brick-min]').addEventListener('change', () => { if (q('[data-brick-toggle]').checked) refresh() })
  return { draw, selectFigure, dispose: () => { revision++; controller?.abort() },
    evidence: () => result ? { ...result, row_mapping: mapping, visible: q('[data-brick-toggle]').checked, placement_status: 'user-calibrated hypothesis', reconstruction_positions_visible: q('[data-reconstruction-toggle]').checked, reconstruction_notice: reconstructionNotice() } : null }
}
