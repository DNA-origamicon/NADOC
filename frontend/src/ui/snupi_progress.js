/** Dynamics counters are distinct from the static solver's n_steps load setting. */
export function snupiDynamicsProgress(node) {
  if (node?.engine !== 'snupi' || !node.dynamics) return null
  const number = x => x != null && Number.isFinite(Number(x)) ? Number(x) : null
  const total = number(node.total_steps) || 60000
  const raw = number(node.current_step ?? node.step)
  const step = node.status === 'completed' ? total : raw == null ? null : Math.max(0, Math.min(total, raw))
  const indeterminate = ['preparing', 'queued', 'running'].includes(node.status) && (node.progress_indeterminate || step == null)
  const fraction = step == null ? 0 : step / total
  const pct = Math.round(fraction * 1000) / 10
  const pending = step === 0 ? 'Dynamics pending' : 'Waiting for dynamics progress'
  const text = step == null ? `Dynamics progress unavailable · ${total.toLocaleString()} steps planned`
    : indeterminate ? `${pending} · ${total.toLocaleString()} steps planned`
    : `${pct}% dynamics · ${(step ?? 0).toLocaleString()} / ${total.toLocaleString()} steps · ${(total - (step ?? 0)).toLocaleString()} left`
  const attempt = Number(node.attempt) || 0
  return { fraction, indeterminate, text: text + (attempt ? ` · retry ${attempt}` : '')
    + (node.progress_last_known ? ' · last known (sync unavailable)' : '') }
}
