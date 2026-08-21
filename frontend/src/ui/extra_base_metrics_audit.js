/** Help ▸ Extra-Base Metrics Audit — measured states, windows and validation. */
import { docHeaders } from '../shared/doc_id.js'
import { createExtraBaseComparisonViewer } from './extra_base_cluster_viewer.js'
import './extra_base_metrics_audit.css'

const PANEL_ORDER = ['hop_position', 'pose_orientation', 'environment']
const STATE_COLORS = ['#d29922', '#a371f7', '#3fb950', '#f85149', '#58a6ff', '#db61a2']

const pct = value => `${(100 * Number(value || 0)).toFixed(1)}%`
const num = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—'
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]))

export function populationRows(panel) {
  if (!panel?.ready) return []
  return (panel.clusters ?? []).map((cluster, index) => ({
    state: index + 1,
    population: cluster.population,
    sem: cluster.population_sem,
    visits: cluster.visits,
    nEff: cluster.n_eff,
    publishable: panel.verdict === 'switching' && !panel.confidence?.preliminary,
  }))
}

export function stableWindowCoverage(insert) {
  const stable = Number(insert?.n_stable_samples ?? 0)
  const total = Number(insert?.n_samples ?? 0)
  return total > 0 ? stable / total : 0
}

export function stateCloudSvg(cloud) {
  const points = (cloud?.points ?? []).filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]))
  if (!points.length) return '<div class="xbma-no-viz">No stable state cloud</div>'
  const xs = points.map(p => p[0]); const ys = points.map(p => p[1])
  const loX = Math.min(...xs); const hiX = Math.max(...xs); const loY = Math.min(...ys); const hiY = Math.max(...ys)
  const sx = x => 28 + 244 * (x - loX) / Math.max(1e-9, hiX - loX)
  const sy = y => 132 - 108 * (y - loY) / Math.max(1e-9, hiY - loY)
  const dots = points.map(([x, y, state]) => `<circle cx="${sx(x).toFixed(1)}" cy="${sy(y).toFixed(1)}" r="2.2" fill="${STATE_COLORS[Math.max(0, state) % STATE_COLORS.length]}" fill-opacity=".55"/>`).join('')
  return `<svg class="xbma-state-cloud" viewBox="0 0 290 155" role="img" aria-label="State-colored hop-coordinate occupancy cloud">
    <line x1="28" y1="132" x2="276" y2="132"/><line x1="28" y1="18" x2="28" y2="132"/>${dots}
    <text x="150" y="151">t along 3′→5′ hop (${num(loX)}…${num(hiX)})</text>
    <text transform="translate(9 93) rotate(-90)">hop bow (${num(loY)}…${num(hiY)})</text></svg>`
}

export function stableTimelineSvg(insert) {
  const windows = insert?.stable_windows ?? []
  const maxFrame = Math.max(1, ...windows.map(w => Number(w.frame_stop || 0)))
  const rects = windows.map(w => {
    const x = 5 + 280 * Number(w.frame_start || 0) / maxFrame
    const width = Math.max(1, 280 * (Number(w.frame_stop || 0) - Number(w.frame_start || 0)) / maxFrame)
    return `<rect x="${x.toFixed(1)}" y="5" width="${width.toFixed(1)}" height="10" rx="2"/>`
  }).join('')
  return `<svg class="xbma-timeline" viewBox="0 0 290 20" role="img" aria-label="Stable trajectory windows"><rect class="track" x="5" y="5" width="280" height="10" rx="2"/>${rects}</svg>`
}

export function cpdMarkup(cpd) {
  if (!cpd) return ''
  const d = cpd.d_mid_A
  const position = Math.min(100, Math.max(0, 100 * (d.mean - 3) / 15))
  return `<section class="xbma-cpd"><header><strong>CPD weld-pair reaction coordinates</strong><span>${cpd.production_ns} ns · ${cpd.n_frames} frames</span></header>
    <div class="xbma-cpd-grid"><div><div class="xbma-distance-axis"><i style="left:${position}%"></i><b style="width:10%"></b></div>
      <strong>d_mid ${num(d.mean)} ± ${num(d.sd)} Å</strong><small>range ${num(d.min)}–${num(d.max)} Å · reactive distance &lt; ${cpd.reactive_corner.d_max_A} Å</small></div>
      <div class="xbma-eta-ring"><i></i><span>η<br>${num(cpd.eta_deg.mean, 1)}° ± ${num(cpd.eta_deg.sd, 1)}°</span></div>
      <div><strong>Reactive corner ${cpd.reactive_corner.n}/${cpd.reactive_corner.total}</strong><small>${cpd.n_below_8A} frames below 8 Å · ${cpd.n_below_6A} below 6 Å</small><small>${esc(cpd.provenance)}</small></div></div>
  </section>`
}

function panelMarkup(name, panel, label) {
  const populations = populationRows(panel)
  const verdict = panel?.ready ? panel.verdict : 'not ready'
  const rows = populations.length
    ? populations.map(row => `<tr><td><i class="xbma-state-dot" style="background:${STATE_COLORS[(row.state - 1) % STATE_COLORS.length]}"></i>S${row.state}</td><td><span class="xbma-pop-bar"><i style="width:${100 * row.population}%;background:${STATE_COLORS[(row.state - 1) % STATE_COLORS.length]}"></i></span>${pct(row.population)} ± ${pct(row.sem)}</td><td>${row.visits ?? 0}</td><td>${num(row.nEff, 1)}</td></tr>`).join('')
    : '<tr><td colspan="4">No state populations available</td></tr>'
  return `<section class="xbma-panel" data-metric-panel="${name}">
    <header><strong>${esc(label)}</strong><span class="xbma-verdict ${esc(verdict)}">${esc(verdict)}</span></header>
    <div class="xbma-panel-stats">k ${panel?.k ?? '—'} · silhouette ${num(panel?.silhouette)} · transitions ${panel?.transitions ?? '—'} · lag-1 ${num(panel?.pc1_lag1)}</div>
    <div class="xbma-metric-list">${esc((panel?.metrics ?? []).join(' · ') || panel?.reason || 'No metrics')}</div>
    <table><thead><tr><th>State</th><th>Population ± SEM</th><th>Visits</th><th>N_eff</th></tr></thead><tbody>${rows}</tbody></table>
  </section>`
}

function insertMarkup(insert, labels, stableOnly) {
  const coverage = stableWindowCoverage(insert)
  const failures = Object.entries(insert.failure_counts ?? {})
    .sort((a, b) => b[1] - a[1]).map(([name, count]) => `${name}: ${count}`).join(' · ') || 'none'
  const windows = (insert.stable_windows ?? []).map(w =>
    `${w.frame_start}–${w.frame_stop} (${w.n_samples} samples)`).join(' · ') || 'none'
  const panels = PANEL_ORDER.map(name => panelMarkup(name, insert.panels?.[name], labels[name])).join('')
  return `<article class="xbma-insert" data-extra-base="true">
    <div class="xbma-insert-head"><strong>${esc(insert.crossover_id?.slice(0, 8))} · insert k${insert.insert_k} · ${esc(insert.base)}</strong>
      <span>${pct(insert.valid_fraction)} valid · ${pct(coverage)} stable coverage</span></div>
    <div class="xbma-window-bar" title="Stable-window coverage"><i style="width:${100 * coverage}%"></i></div>
    ${stableTimelineSvg(insert)}
    <div class="xbma-state-viz"><div><strong>Hop-coordinate occupancy</strong>${stateCloudSvg(insert.state_cloud)}</div></div>
    <details ${stableOnly ? 'open' : ''}><summary>Stable windows (${insert.stable_windows?.length ?? 0})</summary><div>${esc(windows)}</div></details>
    <details><summary>Rejected-frame metrics</summary><div>${esc(failures)}</div></details>
    <div class="xbma-panels">${panels}</div>
    <div class="xbma-agreement">Cross-metric ARI: ${esc(Object.entries(insert.panel_agreement_ari ?? {}).map(([k, v]) => `${k.replace('__', ' ↔ ')} ${num(v)}`).join(' · ') || '—')}</div>
  </article>`
}

function comparisonReadout(clusterI, clusterI1) {
  const c1I = clusterI?.medoid?.atoms_A?.["C1'"]
  const c1I1 = clusterI1?.medoid?.atoms_A?.["C1'"]
  if (!c1I || !c1I1) return 'No paired medoid coordinates available'
  const delta = c1I1.map((value, index) => Number(value) - Number(c1I[index]))
  const distance = Math.hypot(...delta)
  return `<strong>Aligned C1′ separation ${num(distance, 2)} Å</strong> · Δ(i→i+1) = (${num(delta[0], 2)}, ${num(delta[1], 2)}, ${num(delta[2], 2)}) Å<br>
    i frame ${clusterI.medoid.frame?.toLocaleString?.() ?? clusterI.medoid.frame} · i+1 frame ${clusterI1.medoid.frame?.toLocaleString?.() ?? clusterI1.medoid.frame} · positions remain in their measured canonical frames`
}

function comparisonOptions(side) {
  return (side?.clusters ?? []).map((cluster, index) => `<option value="${index}">${index === 0 ? 'Most likely' : `Cluster ${index + 1}`} · ${pct(cluster.population)}</option>`).join('')
}

function comparisonMarkup(pooled) {
  const sideI = pooled?.sides?.find(side => side.side === 'i')
  const sideI1 = pooled?.sides?.find(side => side.side === 'i+1')
  if (!sideI?.ready || !sideI1?.ready) return ''
  const atomisticReady = [...sideI.clusters, ...sideI1.clusters].every(cluster => cluster.medoid?.atomistic)
  return `<article class="xbma-comparison" data-comparison-panel>
    <header><div><strong>Aligned reciprocal extra bases</strong><small>Both medoids share X interhelix · Y helix axis · Z out-of-plane coordinates; no medoid-to-medoid fit is applied.</small>
      <small>i: ${sideI.n_observations?.toLocaleString?.() ?? sideI.n_observations} stable positions · ${sideI.n_crossovers} sites · k ${sideI.k} · silhouette ${num(sideI.silhouette)} &nbsp;|&nbsp; i+1: ${sideI1.n_observations?.toLocaleString?.() ?? sideI1.n_observations} stable positions · ${sideI1.n_crossovers} sites · k ${sideI1.k} · silhouette ${num(sideI1.silhouette)}</small></div>
      <div class="xbma-comparison-controls"><label><i>i / left</i><select data-comparison-side="i">${comparisonOptions(sideI)}</select></label>
        <label><i>i+1 / right</i><select data-comparison-side="i+1">${comparisonOptions(sideI1)}</select></label>
        <span>Representation</span><button type="button" class="active" data-comparison-representation="schematic">Schematic</button><button type="button" data-comparison-representation="atomistic" ${atomisticReady ? '' : 'disabled'}>Atomistic</button></div></header>
    <div class="xbma-comparison-view" aria-label="Orbitable aligned i and i+1 extra-base comparison"></div>
    <div class="xbma-comparison-legend"><span class="side-i">● i / left</span><span class="side-i1">● i+1 / right</span><span>wireframes = per-cluster positional spread</span><span>shared cylinders = mean medoid helix spacing</span></div>
    <div class="xbma-comparison-readout">${comparisonReadout(sideI.clusters[0], sideI1.clusters[0])}</div>
  </article>`
}

function pooledMarkup(pooled) {
  return `<section class="xbma-pooled-intro"><strong>Reciprocal Holliday-junction position ensembles</strong>
    <span>${esc(pooled.classification)} · ${pooled.n_unpaired_inserts ?? 0} unpaired inserts excluded · fit capped at ${pooled.max_fit_samples_per_side?.toLocaleString?.() ?? pooled.max_fit_samples_per_side} balanced samples per side</span></section>
    ${comparisonMarkup(pooled)}`
}

function mountPooledViewer(root, pooled, comparisonViewerFactory) {
  if (!comparisonViewerFactory) return []
  const selected = { i: 0, 'i+1': 0 }
  const sideI = pooled?.sides?.find(side => side.side === 'i')
  const sideI1 = pooled?.sides?.find(side => side.side === 'i+1')
  const comparisonContainer = root.querySelector('.xbma-comparison-view')
  if (!comparisonContainer || !sideI?.ready || !sideI1?.ready) return []
  const viewer = comparisonViewerFactory(comparisonContainer, { sideI, sideI1, initialIndices: selected })
  const update = () => {
    viewer.setClusters?.({ ...selected })
    root.querySelector('.xbma-comparison-readout').innerHTML = comparisonReadout(
      sideI.clusters[selected.i], sideI1.clusters[selected['i+1']],
    )
  }
  root.querySelectorAll('[data-comparison-side]').forEach(select => select.addEventListener('change', () => {
    selected[select.dataset.comparisonSide] = Number(select.value)
    update()
  }))
  root.querySelectorAll('[data-comparison-representation]').forEach(button => button.addEventListener('click', () => {
    if (button.disabled) return
    viewer.setRepresentation?.(button.dataset.comparisonRepresentation)
    root.querySelectorAll('[data-comparison-representation]').forEach(candidate => candidate.classList.toggle('active', candidate === button))
  }))
  return [viewer]
}

export function renderExtraBaseMetricsAudit(root, bundle, options = {}) {
  const { sourceIndex = 0, stableOnly = true, panelVisibility = {}, comparisonViewerFactory = null } = options
  const source = bundle.sources?.[sourceIndex]
  if (!source) {
    root.innerHTML = '<div class="xbma-empty">No processed extra-base evidence is available. Run exp53 refresh.</div>'
    return
  }
  const pooled = source.pooled_positions?.ready ? source.pooled_positions : null
  root.innerHTML = `<div class="xbma-source-summary">
      <strong>${esc(source.part)}</strong><span>${esc(source.role)}</span>
      <span>${source.n_frames?.toLocaleString?.() ?? source.n_frames} trajectory frames</span>
      <span>${source.topology_pass ? '✓ no seed ring piercing' : '⚠ topology not validated'}</span>
      <span>${esc(source.job)}</span>
    </div>${cpdMarkup(source.cpd_reference)}<div class="xbma-context"><strong>Trajectory context</strong> ${esc((source.dcd ?? []).join?.(', ') ?? source.dcd)}<br>
      <strong>Integrity filter</strong> ${esc(Object.entries(source.filters ?? {}).map(([key, value]) => `${key}=${value}`).join(' · '))}</div>
    ${pooled ? pooledMarkup(pooled) : (source.inserts ?? []).map(insert => insertMarkup(insert, bundle.metric_panels, stableOnly)).join('')}`
  for (const name of PANEL_ORDER) {
    const visible = panelVisibility[name] !== false
    root.querySelectorAll(`[data-metric-panel="${name}"]`).forEach(el => { el.hidden = !visible })
  }
  return mountPooledViewer(root, pooled, comparisonViewerFactory)
}

function modalMarkup() {
  const modal = document.createElement('div')
  modal.id = 'extra-base-metrics-audit'
  modal.className = 'xbma-modal'
  modal.innerHTML = `<header class="xbma-header"><div><strong>Extra-Base Metrics Audit</strong>
    <small>Read-only clustered extra-base positions in reciprocal Holliday-junction frames.</small></div>
    <button class="xbma-close">Close</button></header>
    <div class="xbma-controls"><label>Evidence source <select class="xbma-source"></select></label>
      <label><input class="xbma-extra-only" type="checkbox" checked> Extra bases only</label>
      <label class="xbma-legacy-control"><input class="xbma-stable-only" type="checkbox" checked> Stable windows only</label>
      <label class="xbma-legacy-control"><input data-panel-toggle="hop_position" type="checkbox" checked> Hop position</label>
      <label class="xbma-legacy-control"><input data-panel-toggle="pose_orientation" type="checkbox" checked> Pose / orientation</label>
      <label class="xbma-legacy-control"><input data-panel-toggle="environment" type="checkbox" checked> Environment</label></div>
    <main class="xbma-body"></main>`
  return modal
}

export function initExtraBaseMetricsAudit({ setMenuToggle = () => {}, comparisonViewerFactory = createExtraBaseComparisonViewer, fetchAudit = async () => {
  const response = await fetch('/api/design/extra-base-metrics-audit', { headers: docHeaders() })
  if (!response.ok) throw new Error(`Metrics audit request failed (${response.status})`)
  return response.json()
} } = {}) {
  const menu = document.getElementById('menu-help-extra-base-metrics-audit')
  const modal = modalMarkup()
  document.body.appendChild(modal)
  const body = modal.querySelector('.xbma-body')
  const sourceSelect = modal.querySelector('.xbma-source')
  let bundle = null
  let open = false
  let viewers = []
  const panelVisibility = Object.fromEntries(PANEL_ORDER.map(name => [name, true]))

  function disposeViewers() {
    viewers.forEach(viewer => viewer?.dispose?.())
    viewers = []
  }
  function render() {
    if (!bundle) return
    disposeViewers()
    const sourceIndex = Number(sourceSelect.value || 0)
    modal.classList.toggle('has-pooled', Boolean(bundle.sources?.[sourceIndex]?.pooled_positions?.ready))
    viewers = renderExtraBaseMetricsAudit(body, bundle, {
      sourceIndex,
      stableOnly: modal.querySelector('.xbma-stable-only').checked,
      panelVisibility,
      comparisonViewerFactory,
    })
    body.classList.toggle('show-context', !modal.querySelector('.xbma-extra-only').checked)
  }
  function close() {
    open = false
    disposeViewers()
    modal.classList.remove('visible')
    setMenuToggle('menu-help-extra-base-metrics-audit', false)
  }
  async function show() {
    if (open) { close(); return }
    open = true
    modal.classList.add('visible')
    setMenuToggle('menu-help-extra-base-metrics-audit', true)
    body.innerHTML = '<div class="xbma-empty">Loading measured evidence…</div>'
    try {
      bundle = await fetchAudit()
      sourceSelect.innerHTML = bundle.sources.map((s, i) => `<option value="${i}">${esc(s.part)} · ${esc(s.role)}</option>`).join('')
      render()
    } catch (error) {
      body.innerHTML = `<div class="xbma-error">${esc(error.message)}</div>`
    }
  }
  sourceSelect.addEventListener('change', render)
  modal.querySelector('.xbma-stable-only').addEventListener('change', render)
  modal.querySelector('.xbma-extra-only').addEventListener('change', event => {
    body.classList.toggle('show-context', !event.target.checked)
  })
  modal.querySelectorAll('[data-panel-toggle]').forEach(toggle => toggle.addEventListener('change', () => {
    panelVisibility[toggle.dataset.panelToggle] = toggle.checked
    render()
  }))
  modal.querySelector('.xbma-close').addEventListener('click', close)
  menu?.addEventListener('click', show)
  return { show, close, modal }
}
