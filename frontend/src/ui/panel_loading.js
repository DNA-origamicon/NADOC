/** Loading state is scoped to the affected panel, never a workspace-wide blocker. */
const loading = new WeakMap()
const requests = new Map()
export function beginPanelLoading(targets, label = 'Loading…') {
  const elements = [...new Set(targets.filter(Boolean))]
  for (const element of elements) {
    let state = loading.get(element)
    if (!state) {
      const spinner = document.createElement('span')
      spinner.className = 'nadoc-spinner'
      spinner.dataset.panelLoading = 'true'
      spinner.style.marginLeft = '6px'
      spinner.setAttribute('role', 'status')
      spinner.setAttribute('aria-label', label)
      spinner.title = label
      state = { count: 0, spinner, previousBusy: element.getAttribute('aria-busy') }
      loading.set(element, state)
      element.append(spinner)
      element.setAttribute('aria-busy', 'true')
    }
    state.count++
  }
  let ended = false
  return () => {
    if (ended) return
    ended = true
    for (const element of elements) {
      const state = loading.get(element)
      if (--state.count) continue
      state.spinner.remove()
      if (state.previousBusy === null) element.removeAttribute('aria-busy')
      else element.setAttribute('aria-busy', state.previousBusy)
      loading.delete(element)
    }
  }
}

export function recordPanelRequest({ id, phase, path }) {
  if (typeof document === 'undefined') return
  if (phase !== 'start') {
    if (['complete', 'error', 'aborted'].includes(phase)) {
      requests.get(id)?.()
      requests.delete(id)
    }
    return
  }
  const engine = /^\/(md|oxdna|mrdna|cando|snupi|blade|lammps)\/(jobs|queue|available|namd-available|run-dir-status)(?:[/?]|$)/.exec(path)?.[1]
  if (!engine && !/^\/(simulate\/jobs|engines\/status)(?:[/?]|$)/.test(path)) return
  const tab = engine === 'md' ? 'namd' : engine === 'lammps' ? 'oxdna' : engine
  const targets = [document.querySelector('.left-tab-btn[data-tab="dynamics"]')]
  if (tab) targets.push(document.querySelector(`.engine-selector-btn[data-engine="${tab}"]`))
  if (path.includes('/jobs') || path.includes('/queue')) targets.push(document.getElementById('simulate-jobs-toggle'))
  requests.set(id, beginPanelLoading(targets, 'Loading simulation data…'))
}
