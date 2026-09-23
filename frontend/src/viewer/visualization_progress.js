/** Read only progress already exposed by the selected engine's visualization card. */
export function visualizationProgress(doc, engine) {
  const root = doc.getElementById(`${engine === 'namd' ? 'md' : 'oxdna'}-jobs-viz-body`)
  if (!root) return null
  const bars = root.querySelectorAll('progress, [role="progressbar"], [data-trajectory-load-fill], [data-lammps-display-phase] > div > div, [id$="progress-fill"]')
  let current = null
  for (const bar of bars) {
    let visible = true
    // Collapsing the visualization card does not cancel the work.
    for (let node = bar; node && node !== root; node = node.parentElement) {
      if (node.hidden || node.style.display === 'none' || node.dataset.loading === 'false') { visible = false; break }
    }
    if (!visible) continue
    let fraction = null
    if (bar.tagName === 'PROGRESS') fraction = bar.hasAttribute('value') ? bar.value / bar.max : null
    else if (bar.hasAttribute('aria-valuenow')) {
      const min = Number(bar.getAttribute('aria-valuemin') ?? 0), max = Number(bar.getAttribute('aria-valuemax') ?? 100)
      fraction = max > min ? (Number(bar.getAttribute('aria-valuenow')) - min) / (max - min) : null
    } else if (bar.style.width.endsWith('%')) fraction = parseFloat(bar.style.width) / 100
    if (fraction !== null && (!Number.isFinite(fraction) || fraction >= 1)) continue
    current = { fraction: fraction === null ? null : Math.max(0, fraction) }
  }
  return current
}
