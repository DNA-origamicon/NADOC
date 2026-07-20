/**
 * BLADE "Graphs and Metrics" card — the relax summary for the selected job.
 *
 * Deliberately NOT a clone of cando_metrics/snupi_metrics. Those plot per-bp series (RMSF,
 * deviation) that come out of an FEM solve; a relax produces no such series — it produces one
 * settled structure and a handful of scalars describing how far it travelled to get there. So
 * this card is a readout, not a chart.
 *
 * The scalars, and why each is here:
 *   • rmsd_moved  — Kabsch-aligned RMSD from the idealized starting geometry, rigid motion
 *     removed. This is the headline: how much the relax actually did. Near zero means it
 *     barely moved (suspect the run); very large means it restructured (suspect the physics).
 *   • Rg before → after — the collapse/straighten tell. A large drop on an origami usually
 *     means the structure compacted rather than equilibrated.
 *   • bbox diagonal — the same signal in an extent-sensitive form, which catches a straighten
 *     that leaves Rg roughly unchanged.
 *   • platform — a CUDA request that silently fell back to CPU is a ~20x slowdown, so the card
 *     names the platform the run ACTUALLY used, not the one it asked for.
 *
 * Factory: initBladeMetricsCard({ getSelectedJob }) → { sync, refresh }.
 */

const _fmt = (v, digits = 2) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—')

/**
 * Build the summary rows for a completed job (pure; unit-tested).
 * Returns [] when there is nothing to show, so the caller can show placeholder text.
 */
export function summaryRows(job) {
  if (!job || job.status !== 'completed') return []
  const s = job.summary || {}
  const rows = [
    ['Force model', job.correction === 'unified' ? 'CHARMM+OBC2 + learned correction' : 'CHARMM+OBC2'],
    ['Atoms', job.n_atoms ? job.n_atoms.toLocaleString() : '—'],
    ['Moved (RMSD)', `${_fmt(job.rmsd_moved_A)} Å`],
    ['Radius of gyration', `${_fmt(job.rg_before_A, 1)} → ${_fmt(job.rg_after_A, 1)} Å`],
  ]
  if (typeof s.bbox_diag_before_A === 'number' && typeof s.bbox_diag_after_A === 'number') {
    rows.push(['Bounding-box diagonal',
      `${_fmt(s.bbox_diag_before_A, 1)} → ${_fmt(s.bbox_diag_after_A, 1)} Å`])
  }
  rows.push(['Settling time', `${_fmt(job.langevin_ps, 1)} ps @ ${_fmt(job.temp_K, 0)} K`])
  rows.push(['Nonbonded cutoff', `${_fmt(job.nb_cutoff_A, 0)} Å`])
  if (job.platform_used) {
    // Name the fallback explicitly — "CPU" alone reads as a choice rather than a degradation.
    const fell = job.platform === 'CUDA' && job.platform_used === 'CPU'
    rows.push(['Platform', fell ? 'CPU (CUDA unavailable — ~20× slower)' : job.platform_used])
  }
  if (job.sim_seconds) rows.push(['Wall time', `${job.sim_seconds} s`])
  return rows
}

/** Render rows as the card's HTML (pure; unit-tested). '' when there is nothing to show. */
export function renderSummaryHTML(rows) {
  if (!rows.length) return ''
  return `<div style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px">${
    rows.map(([k, v]) =>
      `<span style="color:#8b949e">${k}</span><span style="color:#c9d1d9">${v}</span>`
    ).join('')
  }</div>`
}

export function initBladeMetricsCard({ getSelectedJob = null } = {}) {
  const $ = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null)
  const toggle = $('blade-metrics-toggle')
  const card = $('blade-metrics-card')
  const arrow = $('blade-metrics-arrow')
  const bodyEl = $('blade-metrics-body')

  if (toggle && card) {
    toggle.addEventListener('click', () => {
      const hidden = card.style.display === 'none'
      card.style.display = hidden ? '' : 'none'
      if (arrow) arrow.textContent = hidden ? '▾' : '▸'
    })
  }

  function sync() {
    if (!bodyEl) return
    const job = getSelectedJob?.() || null
    const rows = summaryRows(job)
    bodyEl.innerHTML = rows.length
      ? renderSummaryHTML(rows)
      : '<span style="color:#8b949e">Run a relax to see its summary.</span>'
  }

  return { sync, refresh: sync }
}
