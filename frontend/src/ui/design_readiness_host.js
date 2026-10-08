import { initDesignReadiness } from './design_readiness.js'
import { initDesignReadinessVisibility } from './design_readiness_visibility.js'
import { initDesignReadinessController } from './design_readiness_controller.js'
import { createDesignReadinessActions } from './design_readiness_actions.js'
import { readinessBootDocument, restoreReadinessDocument } from './design_readiness_boot.js'
import { docHeaders, getDocId } from '../shared/doc_id.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import './design_readiness.css'

/** Thin DOM/document adapters; readiness itself is always assessed by the backend. */
export function initDesignReadinessHost({ store, mode = '3d', onSimulate, api, onRestored } = {}) {
  const host = document.getElementById(mode === 'cadnano' ? 'pathview-container' : 'canvas-area')
  if (!host) return null
  const actions = createDesignReadinessActions({
    store, mode, document, window, onSimulate, getDocId, broadcast: nadocBroadcast,
  })
  const widget = initDesignReadiness({ host, onAction: (action, step) => actions.run(action, step), onDismiss: dismiss })
  const visibility = initDesignReadinessVisibility({ widget })
  const fitPanel = () => {
    if (host.clientHeight > 0) host.style.setProperty('--design-readiness-max-height', `${Math.max(0, host.clientHeight - 72)}px`)
  }
  const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(fitPanel) : null
  resizeObserver?.observe(host)
  fitPanel()
  let pendingAction = mode === '3d' ? new URL(location.href).searchParams.get('readiness') : null
  let disposed = false
  let restoring = !!readinessBootDocument(location.href, mode)
    && !store.getState().currentDesign && !store.getState().assemblyActive
  let navigationRunning = false
  let generation = 0

  async function showRequestedAction(action) {
    if (action === 'simulation') await actions.run('simulation')
    else if (action) {
      // A navigation URL may reveal a command, but never executes a topology edit.
      widget.open?.()
      widget.focusStep?.(action === 'validation' ? 'topology' : action)
    }
  }

  async function applyPendingAction(report) {
    if (disposed || restoring || navigationRunning || !pendingAction || !report?.available) return
    const action = pendingAction
    const version = generation
    navigationRunning = true
    try {
      await showRequestedAction(action)
      if (disposed || version !== generation || controller.getReport() !== report) return
      widget.setReport(actions.decorate(report))
      if (pendingAction === action) pendingAction = null
      const url = new URL(location.href)
      url.searchParams.delete('readiness')
      history.replaceState(history.state, '', url)
    } catch (error) {
      // A sibling edit can invalidate the report during navigation. Retain the
      // request for the next fresh report; never leak a rejected event promise.
      if (!disposed && version === generation && controller.getReport() === report) widget.setError(error?.message || 'Wait for the current design to finish loading.')
    } finally {
      if (version === generation) navigationRunning = false
    }
  }

  const controller = initDesignReadinessController({
    store, widget, mode, decorate: report => actions.decorate(report),
    async fetchReport(target, { signal }) {
      const response = await fetch(`/api/design/readiness${target.assembly ? '?assembly=true' : ''}`, {
        headers: docHeaders(), signal,
      })
      if (!response.ok) throw new Error(`Readiness check unavailable (${response.status}).`)
      return response.json()
    },
    onReport: report => { void applyPendingAction(report) },
  })
  function dismiss() {
    generation++
    pendingAction = null
    navigationRunning = false
    controller.dismiss()
  }
  function show() {
    if (disposed) return
    widget.show()
    controller.show()
  }
  const showButton = document.getElementById('menu-view-design-readiness')
  showButton?.addEventListener('click', show)
  function onReset() {
    generation++
    pendingAction = null
    navigationRunning = false
    restoring = false
    widget.resetVisibility()
    controller.reset()
  }
  window.addEventListener('nadoc:document-reset', onReset)
  const unsubscribeBroadcast = nadocBroadcast.onMessage(message => {
    if (message.type === 'session-closed') { onReset(); return }
    if (!nadocBroadcast.isSameDoc(message)) return
    if (mode === '3d' && message.type === 'readiness-action' && message.action === 'simulation') {
      pendingAction = 'simulation'
      controller.refresh()
    }
  })

  if (restoring) {
    const version = generation
    void restoreReadinessDocument({ api, store, href: location.href, mode, onRestored, isDisposed: () => disposed || version !== generation })
      .then(() => {
        if (disposed || version !== generation) return
        restoring = false
        if (!disposed) controller.refresh()
      })
      .catch(error => {
        // Keep the restoration gate closed: a topology-only partial load must
        // not open locked controls or consume the query on a later poll.
        if (!disposed && version === generation) widget.setError(error?.message || 'Could not load this design in 3D.')
      })
  }

  function dispose() {
    if (disposed) return
    disposed = true
    controller.dispose()
    actions.dispose?.()
    visibility.dispose()
    widget.dispose()
    resizeObserver?.disconnect()
    host.style.removeProperty('--design-readiness-max-height')
    unsubscribeBroadcast()
    showButton?.removeEventListener('click', show)
    window.removeEventListener('nadoc:document-reset', onReset)
    window.removeEventListener('pagehide', onPageHide)
    window.removeEventListener('pageshow', onPageShow)
  }
  function onPageHide(event) { if (!event.persisted) dispose() }
  function onPageShow(event) { if (event.persisted) controller.refresh() }
  window.addEventListener('pagehide', onPageHide)
  window.addEventListener('pageshow', onPageShow)
  return { refresh: controller.refresh, show, dispose }
}
