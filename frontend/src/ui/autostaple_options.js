import './autostaple_options.css'
import './cluster_folding_panel.css'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { foldingPlan, foldingPlanText } from './cluster_folding_order.js'

const field = (label, input) => el('label', { className: 'autostaple-field', children: [el('span', { text: label }), input] })
const select = (label, choices) => el('select', { className: 'select', attrs: { 'aria-label': label }, children:
  choices.map(([value, text]) => el('option', { attrs: { value }, text })) })

export function chooseAutostapleMethod() {
  return new Promise(resolve => {
    let choice = null
    const input = select('Method', [['standard', 'Standard'], ['experimental', 'Experimental']])
    const modal = createModal({ title: 'Autostaple method', body: field('Method', input), actions: [
      createButton({ label: 'Cancel', onClick: () => modal.close() }),
      createButton({ label: 'OK', variant: 'primary', onClick: () => { choice = input.value; modal.close() } }),
    ], onClose: () => resolve(choice) })
    modal.root.classList.add('autostaple-options')
    modal.root.setAttribute('aria-label', 'Autostaple method')
    modal.open()
  })
}

export function chooseExperimentalAutostaple({ design, regional }) {
  return new Promise(resolve => {
    let choice = null
    const repeat = select('HC crossover repeat', [['42', '42 bp — alternate repeats'], ['21', '21 bp — every repeat']])
    const pattern = select('Pattern', [['0', 'A'], ['1', 'B']])
    const minimum = el('input', { className: 'input', attrs: { type: 'number', required: true, min: 7, max: 200, step: 1, value: 21, 'aria-label': 'Minimum staple length' } })
    const maximum = el('input', { className: 'input', attrs: { type: 'number', required: true, min: 21, max: 300, step: 1, value: 56, 'aria-label': 'Staple merge limit' } })
    const cap = el('input', { className: 'input', attrs: { type: 'number', required: true, min: 21, max: 300, step: 1, value: 60, 'aria-label': 'Maximum staple length' } })
    const error = el('p', { attrs: { role: 'alert' } })
    const hc = design.lattice_type === 'HONEYCOMB'
    const folding = select('Folding-order routing', [['default', 'Default routing'], ['ordered', 'Use cluster folding order']])
    const gap = el('input', { className: 'input', attrs: { type: 'number', required: true, min: 0.1, max: 20, step: 0.1, value: 2, 'aria-label': 'Temperature gap' } })
    const apply = createButton({ label: 'Apply', variant: 'primary', onClick: () => {
      if (folding.value === 'ordered' && !gap.checkValidity()) { error.textContent = 'Enter a temperature gap from 0.1 to 20 °C.'; return }
      if (!cap.checkValidity()) { error.textContent = 'Enter a whole maximum length between 21 and 300 nt.'; return }
      if (!minimum.checkValidity() || !maximum.checkValidity() || Number(minimum.value) > Number(maximum.value)) {
        error.textContent = 'Enter whole nucleotide counts; minimum must be between 7 and the merge limit (21–300 nt).'
        return
      }
      choice = { crossover_repeat_bp: Number(repeat.value), pattern: Number(pattern.value),
        min_length: Number(minimum.value), max_merged_length: Number(maximum.value), max_staple_length: Number(cap.value) }
      if (folding.value === 'ordered') Object.assign(choice, { folding_order: true, temperature_gap_c: Number(gap.value) })
      modal.close()
    } })
    const canOrder = !regional && foldingPlan(design).stages.length >= 2
    const updateFolding = () => {
      gap.disabled = folding.value !== 'ordered'
      apply.disabled = !hc || (folding.value === 'ordered' && !canOrder)
      pattern.disabled = repeat.value === '21' && folding.value !== 'ordered'
    }
    folding.addEventListener('change', updateFolding)
    updateFolding()
    repeat.addEventListener('change', updateFolding)
    const body = el('div', { children: [
      el('p', { text: regional ? 'Scope: selected region, expanded to every touching staple.' : 'Scope: entire structure.' }),
      !hc ? el('p', { text: 'Experimental routing currently requires a honeycomb lattice.' }) : null,
      field('Folding-order routing', folding),
      el('p', { className: 'folding-plan', text: foldingPlanText(design) }),
      el('p', { className: 'tool-help', text: 'Ordering requires the entire part and at least two distinct stages. The first stage uses 42 bp crossover repeats to favor longer binding domains; later stages use 21 bp repeats and may receive additional nicks. Undefined and inter-cluster crossover sites use the default settings below. Each earlier cluster must exceed the next stage’s median estimated staple Tfold by the requested gap, or nothing is applied.' }),
      field('Temperature gap (°C)', gap),
      el('p', { className: 'tool-help', text: 'Estimates use 10 mM free Mg²⁺ and 200 nM staple. Median separation does not guarantee cooperative folding order; temperature ranges can overlap.' }),
      field('HC crossover repeat', repeat), field('Pattern', pattern),
      el('p', { className: 'tool-help', text: '42 bp retains alternate repeats of each eligible crossover pair. Nicks in omitted repeats are also skipped to favor longer binding domains. Boundaries and protected connections can interrupt the pattern.' }),
      field('Maximum staple length (nt)', cap),
      el('p', { className: 'tool-help', text: 'Hard limit for experimental routing, including insertions, deletions, overhangs, extension bases and junction inserts. Takes priority over growth settings and may add nicks, shortening binding domains. Protected staples above the limit prevent routing. Staples outside the chosen scope remain unchanged.' }),
      field('Minimum staple length (nt)', minimum), field('Staple merge limit (nt)', maximum),
      el('p', { className: 'tool-help', text: 'Growth limits use lattice spans. The merge limit is a growth parameter, not a strict length cap. Short-fragment repair and protected strands may exceed it. Actual length distributions are shown after routing. These settings do not predict folding temperature.' }),
      error,
    ] })
    const modal = createModal({ title: 'Experimental autostaple', body, actions: [
      createButton({ label: 'Cancel', onClick: () => modal.close() }), apply,
    ], onClose: () => resolve(choice) })
    modal.root.classList.add('autostaple-options')
    modal.root.setAttribute('aria-label', 'Experimental autostaple')
    modal.open()
  })
}

export function showExperimentalAutostapleReport(report) {
  const distribution = (title, values) => el('div', { children: [el('h3', { text: title }),
    el('p', { text: Object.entries(values ?? {}).map(([nt, count]) => `${nt} nt: ${count}`).join(' · ') || 'No staples' })] })
  const modal = createModal({ title: 'Experimental autostaple results', body: el('div', { children: [
    el('p', { text: `${report.crossover_repeat_bp} bp repeat · pattern ${report.pattern === 0 ? 'A' : 'B'}` }),
    report.folding_result ? foldingResult(report.folding_result) : null,
    distribution('Staple lengths', report.staple_lengths), distribution('Binding-domain spans', report.domain_lengths),
    el('p', { className: 'tool-help', text: 'Domain spans are lattice bp spans; insertions, deletions and unpaired domains can change hybridized lengths. Results cover the routed scope, including protected staples.' }),
  ] }), actions: [createButton({ label: 'Close', onClick: () => modal.close() })] })
  modal.root.setAttribute('aria-label', 'Experimental autostaple results')
  modal.open()
}

function foldingResult(result) {
  return el('section', { children: [
    el('h3', { text: `Folding order — achieved median gap ≥ ${result.gap_c} °C` }),
    ...result.clusters.map(c => el('p', { text: `Stage ${c.stage} · ${c.name}: median ${c.median_c.toFixed(1)} °C (${c.min_c.toFixed(1)}–${c.max_c.toFixed(1)} °C; ${c.count} staples)` })),
    ...result.stages.map(s => el('p', { text: `Stage ${s.stage}: ${s.crossover_repeat_bp} bp repeats; ${s.length_cap_nt == null ? 'baseline lengths' : `${s.length_cap_nt} nt cap`}; ${s.added_nicks} added nicks` })),
    el('p', { text: `${result.default_routed_staples} staples outside the temperature objective (Undefined or crossing cluster boundaries).` }),
    el('p', { className: 'tool-help', text: 'Estimated independent-staple Tfold at 10 mM Mg²⁺ / 200 nM staple. Temperature distributions may overlap. Cooperative folding order requires experimental validation.' }),
  ] })
}
