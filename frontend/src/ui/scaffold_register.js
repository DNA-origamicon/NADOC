import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

let active = null

export function showScaffoldRegister({ api }) {
  if (active?.isOpen()) return active
  let result = null
  let busy = false
  const body = el('div')
  body.append(el('p', { text: 'Compare symbolic scaffold start positions with Aksel’s fixed-route register sweep. The scaffold is circular: the displayed nick is a sequence origin, not a physical break. Staple routes stay fixed.' }))
  body.append(el('p', { text: 'Higher Q is better (sum of staple log folding probabilities per paired base). Q is a model score, not a predicted experimental yield.' }))
  const inputs = {}
  const settings = el('div', { attrs: { style: 'display:grid;grid-template-columns:1fr 120px;gap:8px;align-items:center' } })
  for (const [key, label, value] of [
    ['temperature_c', 'Temperature (°C)', 50], ['scaffold_nM', 'Scaffold (nM)', 10],
    ['staple_nM', 'Staples (nM)', 100], ['magnesium_mM', 'Mg²⁺ (mM)', 12.5], ['tris_mM', 'Tris (mM)', 40],
  ]) {
    const input = el('input', { attrs: { type: 'number', step: 'any', min: '0', value, 'aria-label': label } })
    inputs[key] = input
    input.addEventListener('input', () => { result = null; table.replaceChildren(); chart.style.display = 'none'; apply.disabled = true })
    settings.append(el('label', { text: label, children: [input], attrs: { style: 'display:contents' } }))
  }
  const status = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const table = el('div', { attrs: { style: 'max-height:280px;overflow:auto' } })
  const chart = el('canvas', { attrs: { width: 640, height: 150, 'aria-label': 'Quality score across scaffold start positions', style: 'width:100%;height:150px;display:none' } })
  const select = el('select', { attrs: { 'aria-label': 'Scaffold start candidate', style: 'width:100%' } })
  let selectedCut = 0
  select.addEventListener('change', () => { selectedCut = Number(select.value); apply.disabled = busy || selectedCut === 0 || !result })
  function setBusy(value) {
    busy = value
    run.disabled = value
    for (const input of Object.values(inputs)) input.disabled = value
    select.disabled = value
    apply.disabled = value || !result || selectedCut === 0
  }
  function render(data) {
    selectedCut = data.best.cut_index
    select.replaceChildren()
    const candidates = [...data.top]
    if (!candidates.some(c => c.cut_index === 0)) candidates.push(data.current)
    for (const c of candidates) {
      select.append(el('option', { text: `${c.cut_index === 0 ? 'Current' : `Start +${c.cut_index} nt`} · ${c.helix_id}:${c.bp} ${c.direction} · Q ${c.q.toPrecision(7)} · ΔQ ${c.delta_q.toPrecision(4)}`, attrs: { value: c.cut_index } }))
    }
    select.value = String(selectedCut)
    table.replaceChildren(select)
    status.textContent = `${data.candidate_count.toLocaleString()} eligible starts · ${data.scaffold_nt.toLocaleString()} nt · ${data.staple_count} staples · ${data.elapsed_seconds.toFixed(3)} s. Current Q ${data.current.q.toPrecision(7)}; best ΔQ ${data.best.delta_q.toPrecision(4)}.`
    if (data.ignored_terminal_staple_nt) status.textContent += ` ${data.ignored_terminal_staple_nt} unpaired terminal staple bases excluded from this duplex model.`
    const ctx = chart.getContext('2d')
    if (ctx) {
      chart.style.display = 'block'
      ctx.clearRect(0, 0, 640, 150)
      const qs = data.scores.map(s => s.q)
      const low = Math.min(...qs), high = Math.max(...qs), span = high - low || 1
      ctx.strokeStyle = '#58a6ff'; ctx.beginPath()
      data.scores.forEach((s, i) => {
        const x = 20 + 600 * s.cut_index / data.scaffold_nt, y = 125 - 100 * (s.q - low) / span
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y)
      })
      ctx.stroke(); ctx.fillStyle = '#8b949e'; ctx.font = '12px sans-serif'
      ctx.fillText('Symbolic start position (nt)', 220, 145)
    }
  }
  const run = createButton({ label: 'Evaluate all starts', variant: 'primary', onClick: async () => {
    if (busy) return
    result = null; table.replaceChildren(); chart.style.display = 'none'; setBusy(true)
    status.textContent = 'Evaluating scaffold registers…'
    try {
      const settings = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, Number(input.value)]))
      if (Object.values(inputs).some(input => !input.value.trim()) || Object.values(settings).some(v => !Number.isFinite(v))) throw new Error('Enter a finite value for every condition.')
      const data = await api.sweepScaffoldRegister(settings)
      if (!data) throw new Error(api.lastErrorMessage?.() || 'Could not evaluate this design.')
      if (!modal.isOpen()) return
      result = data; render(data)
    } catch (e) { status.textContent = e.message }
    finally { setBusy(false) }
  } })
  const apply = createButton({ label: 'Apply selected start', disabled: true, onClick: async () => {
    if (!result || busy || selectedCut === 0) return
    setBusy(true)
    try {
      const updated = await api.applyScaffoldRegister(result, selectedCut)
      if (!updated) throw new Error(api.lastErrorMessage?.() || 'Could not apply the start. Run the sweep again.')
      result = null; table.replaceChildren(); chart.style.display = 'none'
      status.textContent = 'Applied the symbolic scaffold start and regenerated staple sequences. Undo restores the previous assignment.'
    } catch (e) { result = null; status.textContent = e.message }
    finally { setBusy(false) }
  } })
  body.append(settings, status, chart, table, el('p', { children: [el('a', { text: 'Aksel et al., PNAS 2024 — model and assumptions', attrs: { href: 'https://doi.org/10.1073/pnas.2406769121', target: '_blank', rel: 'noopener noreferrer' } })] }))
  const modal = createModal({ title: 'Scaffold sequence start — experimental', size: 'lg', body, actions: [run, apply], onClose: () => { active = null } })
  active = modal; modal.open(); return modal
}
