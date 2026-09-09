/** Non-modal, accessible preparation progress. Never takes focus or blocks the canvas. */
export function initAnimationPreparationProgress({ host, onCancel, now = () => Date.now() }) {
  if (!host) return { start() {}, update() {}, ready() {}, clear() {}, error() {} }
  const root = document.createElement('div')
  root.dataset.role = 'animation-preparation'
  root.style.cssText = 'display:none;padding:6px 0;font-size:var(--text-xs);color:#8b949e'
  const label = document.createElement('div')
  label.setAttribute('role', 'status')
  label.setAttribute('aria-live', 'polite')
  const row = document.createElement('div')
  row.style.cssText = 'display:flex;align-items:center;gap:8px'
  const progress = document.createElement('progress')
  progress.max = 1
  progress.setAttribute('aria-label', 'Animation frame preparation')
  progress.style.cssText = 'flex:1;min-width:0;width:100%;height:7px;accent-color:#58a6ff'
  const cancel = document.createElement('button')
  cancel.type = 'button'; cancel.textContent = 'Cancel'
  cancel.addEventListener('click', () => onCancel?.())
  row.append(progress, cancel); root.append(label, row); host.append(root)
  let started = 0, timer = null, text = '', detail = ''
  const paint = () => { label.textContent = `${text}${detail}${started ? ` · ${Math.floor((now() - started) / 1000)}s elapsed` : ''}` }
  const stopTimer = () => { if (timer) clearInterval(timer); timer = null; started = 0 }
  function start(message = 'Preparing preview frames') {
    stopTimer(); started = now(); text = message; detail = ''
    root.style.display = ''; row.style.display = ''; cancel.hidden = false
    progress.removeAttribute('value'); paint(); timer = setInterval(paint, 1000)
  }
  function update(event) {
    if (!timer) start()
    const phase = event.stage || event.phase
    text = event.label || ({ geometry: 'Preparing model states', traj_load: 'Loading trajectory', load: 'Loading trajectory', traj_frames: 'Preparing preview frames', frames: 'Preparing preview frames' }[phase] || 'Preparing preview')
    const total = Number(event.total), done = Number(event.done)
    if (total > 0 && Number.isFinite(done)) {
      progress.value = Math.max(0, Math.min(1, done / total))
      detail = ` · ${done.toLocaleString()} / ${total.toLocaleString()}`
    } else { progress.removeAttribute('value'); detail = '' }
    paint()
  }
  function ready() {
    stopTimer(); text = 'Preview ready'; detail = ''; progress.value = 1
    root.style.display = ''; cancel.hidden = true; paint()
  }
  function clear() { stopTimer(); root.style.display = 'none' }
  function error(message) { stopTimer(); root.style.display = ''; row.style.display = 'none'; text = message; detail = ''; paint() }
  return { start, update, ready, clear, error }
}
