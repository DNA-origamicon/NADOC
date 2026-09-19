import { clearProcessLog, processLogSnapshot, PROCESS_LOG_LIMIT } from '../perf/process_log.js'
import './process_log.css'

const duration = ms => ms < 1000 ? `${ms.toFixed(1)} ms` : ms < 60000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.floor(ms / 60000)}m ${((ms % 60000) / 1000).toFixed(1)}s`
let panel
export function openProcessLog() {
  if (panel) { panel.querySelector('input').focus(); return }
  const returnFocus = document.activeElement
  panel = document.createElement('section')
  panel.id = 'process-log'
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-labelledby', 'process-log-title')
  panel.innerHTML = `<header><strong id="process-log-title">Process Log</strong><button type="button" data-close aria-label="Close process log">Close</button></header>
    <p>Live timings for instrumented API requests and design operations in this tab. API duration includes response parsing, not completion of background simulation jobs. Latest ${PROCESS_LOG_LIMIT} records; reload starts a new log. With Autoscroll off, the displayed rows stay fixed; recording continues. Use Refresh to show the latest timings.</p>
    <div class="process-log-controls"><input aria-label="Filter processes" placeholder="Filter processes…"><select aria-label="Sort processes"><option value="recent">Newest first</option><option value="slow">Longest first</option></select><label><input type="checkbox" data-autoscroll> Autoscroll</label><button type="button" data-refresh>Refresh</button><button type="button" data-export>Export JSON</button><button type="button" data-clear>Clear completed</button></div>
    <p data-summary></p><div class="process-log-table"><table><thead><tr><th>Started</th><th>Process / phases</th><th>Status</th><th>Duration</th></tr></thead><tbody></tbody></table></div><footer><button type="button" data-prev>Previous</button><span data-page></span><button type="button" data-next>Next</button></footer>`
  const current = panel
  document.body.append(current)
  let page = 0
  const filter = current.querySelector('input')
  const sort = current.querySelector('select')
  const autoscroll = current.querySelector('[data-autoscroll]')
  const scroller = current.querySelector('.process-log-table')
  const elapsed = entry => entry.durationMs ?? Math.max(0, performance.now() - entry.startedAt)
  function render() {
    const snapshot = processLogSnapshot()
    const rows = snapshot.entries.filter(entry => `${entry.label} ${entry.kind} ${entry.status} ${entry.detail ?? ''}`.toLowerCase().includes(filter.value.toLowerCase()))
    rows.sort(sort.value === 'slow' ? (a, b) => elapsed(b) - elapsed(a) : (a, b) => b.startedAt - a.startedAt)
    const pages = Math.max(1, Math.ceil(rows.length / 100))
    page = Math.min(page, pages - 1)
    current.querySelector('[data-summary]').textContent = `${rows.length} matching / ${snapshot.entries.length} recorded · ${snapshot.entries.filter(e => e.status === 'Running').length} running · ${snapshot.discarded} older records discarded`
    current.querySelector('[data-page]').textContent = `Page ${page + 1} of ${pages}`
    current.querySelector('[data-prev]').disabled = page === 0
    current.querySelector('[data-next]').disabled = page === pages - 1
    const body = current.querySelector('tbody')
    body.replaceChildren()
    for (const entry of rows.slice(page * 100, (page + 1) * 100)) {
      const row = body.insertRow()
      row.insertCell().textContent = new Date(entry.startedWall).toLocaleTimeString()
      const name = row.insertCell()
      name.textContent = `${entry.kind}: ${entry.label}`
      if (entry.detail) {
        const detail = document.createElement('pre')
        detail.textContent = entry.detail
        name.append(detail)
      }
      row.insertCell().textContent = entry.status
      row.insertCell().textContent = `${duration(elapsed(entry))}${entry.status === 'Running' ? ' elapsed' : ''}`
    }
    if (!rows.length) body.insertRow().insertCell().textContent = 'No recorded processes match.'
  }
  function refresh() {
    const scrollTop = scroller.scrollTop
    const scrollLeft = scroller.scrollLeft
    render()
    scroller.scrollTop = autoscroll.checked ? 0 : scrollTop
    scroller.scrollLeft = scrollLeft
  }
  const timer = setInterval(() => {
    if (autoscroll.checked) { page = 0; refresh() }
  }, 500)
  autoscroll.onchange = () => {
    if (autoscroll.checked) { page = 0; refresh() }
  }
  current.querySelector('[data-refresh]').onclick = refresh
  function close() { clearInterval(timer); current.remove(); panel = null; returnFocus?.focus() }
  current.querySelector('[data-close]').onclick = close
  current.addEventListener('keydown', event => { if (event.key === 'Escape') { event.stopPropagation(); close() } })
  filter.oninput = sort.onchange = () => { page = 0; render() }
  current.querySelector('[data-clear]').onclick = () => { clearProcessLog(); render() }
  current.querySelector('[data-prev]').onclick = () => { page--; render() }
  current.querySelector('[data-next]').onclick = () => { page++; render() }
  current.querySelector('[data-export]').onclick = () => {
    const snapshot = processLogSnapshot()
    const url = URL.createObjectURL(new Blob([JSON.stringify({ ...snapshot, entries: snapshot.entries.map(entry => ({ ...entry, elapsedMs: elapsed(entry) })) }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = 'nadoc-process-log.json'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  render()
  filter.focus()
}
