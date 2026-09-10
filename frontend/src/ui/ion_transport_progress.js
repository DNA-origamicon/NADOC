const STAGES = {
  validate: 'Check transport settings',
  inventory: 'Find and order trajectory files',
  topology: 'Read topology and open trajectories',
  select: 'Identify ion species',
  frames: 'Read trajectory frames',
  current: 'Calculate electrical current',
  crossings: 'Calculate pore crossings',
  occupancy: 'Calculate pore occupancy',
  statistics: 'Calculate current and conductance statistics',
  save: 'Save analysis results',
  receive: 'Receive analysis results',
  'plot-series': 'Prepare plot data',
  'plot-current': 'Draw electrical current plot',
  'plot-crossings': 'Draw pore crossing plot',
}

/** Stable DOM rows keep indeterminate bars animating between progress polls. */
export function initIonTransportProgress(host) {
  const rows = new Map()
  function update(item) {
    if (!host || !item?.stage) return
    let row = rows.get(item.stage)
    if (!row) {
      const el = document.createElement('div')
      el.dataset.ionTransportStage = item.stage
      el.style.cssText = 'margin-top:6px;font-size:11px;color:#8b949e'
      const text = document.createElement('div')
      const bar = document.createElement('progress')
      bar.style.cssText = 'display:block;width:100%;height:7px;margin-top:3px;accent-color:#58a6ff'
      bar.setAttribute('aria-label', STAGES[item.stage] || item.stage)
      el.append(text, bar)
      host.appendChild(el)
      row = { el, text, bar }
      rows.set(item.stage, row)
    }
    const done = Math.max(0, Number(item.done) || 0)
    const total = Math.max(0, Number(item.total) || 0)
    const state = item.state || (total && done >= total ? 'done' : 'running')
    row.el.dataset.state = state
    if (state === 'running' && row.startedAt == null) row.startedAt = performance.now()
    row.bar.max = total || 1
    if (state === 'running' && !total) row.bar.removeAttribute('value')
    else row.bar.value = state === 'done' ? row.bar.max : Math.min(done, total || 1)
    const status = state === 'pending' ? 'Waiting'
      : state === 'error' ? 'Failed'
      : state === 'cancelled' ? 'Not run'
      : state === 'done' ? 'Complete'
      : total ? `${done.toLocaleString()} / ${total.toLocaleString()} (${Math.round(done / total * 100)}%)`
      : `Working… ${Math.floor((performance.now() - row.startedAt) / 1000)}s`
    row.text.textContent = `${STAGES[item.stage] || item.stage} · ${status}${item.detail ? ` · ${item.detail}` : ''}`
    row.bar.setAttribute('aria-valuetext', status)
  }
  function reset(stages = Object.keys(STAGES)) {
    if (!host) return
    host.replaceChildren()
    host.style.display = ''
    rows.clear()
    for (const stage of stages) update({ stage, state: 'pending' })
  }
  function fail(message) {
    for (const [stage, row] of rows) {
      if (row.el.dataset.state === 'running') update({ stage, state: 'error', detail: message })
      else if (row.el.dataset.state === 'pending') update({ stage, state: 'cancelled' })
    }
  }
  function completeAnalysis() {
    // The successful analysis response proves completion even if a poll was lost.
    for (const [stage, row] of rows) {
      if (stage === 'receive') break
      if (row.el.dataset.state !== 'done') update({ stage, done: 1, total: 1 })
    }
  }
  return { reset, update, fail, completeAnalysis, snapshot: data => { for (const stage of data?.stages || []) update(stage) } }
}
