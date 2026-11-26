/** Bounded, read-only loading evidence shared by browser and installed desktop.
 * A frame here is a submitted render pass, never input-to-photon latency.
 * Screenshot inspection remains necessary to establish meaningful visible content.
 */
let current = null
const history = []
let assemblyBuild = { sequence: 0, at: null }

export function recordDesktopAssemblyBuild() {
  assemblyBuild = { sequence: assemblyBuild.sequence + 1, at: performance.now() }
  markDesktopLoad('assembly-meshes-prepared')
}

export function beginDesktopLoad(label) {
  if (current && !current.status) endDesktopLoad('Superseded')
  current = { label, startedAt: performance.now(), marks: [], status: null }
  markDesktopLoad('open-requested')
  globalThis.window?.dispatchEvent(new Event('nadoc:desktop-load-start'))
  return current
}

export function markDesktopLoad(name, detail) {
  if (!current || current.status) return
  current.marks.push({ name, elapsedMs: performance.now() - current.startedAt, ...(detail === undefined ? {} : { detail }) })
}

export function endDesktopLoad(status) {
  if (!current || current.status) return
  markDesktopLoad(status === 'Completed' ? 'first-uncovered-render' : status.toLowerCase())
  current.status = status
  history.push(current)
  if (history.length > 30) history.shift()
}

export function desktopLoadRecords() { return structuredClone({ current, history }) }

export function observeDesktopLoadFrame({ rendered, covered, content }) {
  if (!current || current.status || !current.ready || covered || !rendered || !content) return
  endDesktopLoad('Completed')
}

export function desktopLoadReady() {
  markDesktopLoad('display-prepared')
  if (current && !current.status) current.ready = true
}

export function installDesktopDiagnostics({ renderer, store, addFrameCallback, removeFrameCallback, inspect, snapshot, openFile }) {
  const frame = () => queueMicrotask(() => {
    if (!current || current.status) { removeFrameCallback(frame); return }
    const state = store.getState()
    const content = state.assemblyActive
      ? (state.currentAssembly?.instances?.length ?? 0) > 0
      : (state.currentGeometry?.length ?? state.currentDesign?.helices?.length ?? 0) > 0
    observeDesktopLoadFrame({ rendered: renderer.info.render.calls > 0, content,
      covered: document.hidden || document.getElementById('file-load-progress')?.classList.contains('visible') ||
        !document.getElementById('welcome-screen')?.classList.contains('hidden') })
  })
  const started = () => addFrameCallback(frame)
  window.addEventListener('nadoc:desktop-load-start', started)
  const request = event => {
    const detail = event.detail
    if (/^\/(?:library\/(?:open-part|open-assembly|content)|assembly\/(?:import|geometry)|design\/geometry)/.test(detail.path ?? '')) {
      markDesktopLoad(`request-${detail.phase}`, { path: detail.path, status: detail.status })
    }
  }
  window.addEventListener('nadoc:api-request', request)
  const enabled = new URLSearchParams(location.search).get('desktop-debug') === '1'
  const api = { inspect, snapshot, open: openFile, loads: desktopLoadRecords,
    assemblyBuild: () => ({ ...assemblyBuild }) }
  if (enabled) window.nadocDesktopDiagnostics = api
  return () => {
    removeFrameCallback(frame)
    window.removeEventListener('nadoc:desktop-load-start', started)
    window.removeEventListener('nadoc:api-request', request)
    if (window.nadocDesktopDiagnostics === api) delete window.nadocDesktopDiagnostics
  }
}
