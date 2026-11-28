import './em_tab_availability.css'

const INTRO_KEY = 'nadoc.em.tabIntro.v1'

/** Keep EM discoverable for nanoparticle-bearing parts and assembly sources. */
export function initEMTabAvailability({ store, rightSidebar, api, document = globalThis.document,
  storage = globalThis.localStorage }) {
  const anchor = document.querySelector('#right-tab-strip [data-tab="em"]')
  const window = document.defaultView
  let context, previous = null, generation = 0, popup = null, dismissed = false
  try { dismissed = storage?.getItem(INTRO_KEY) === 'dismissed' } catch {}

  function hideIntro() { popup?.remove(); popup = null }
  function position() {
    if (!popup || !anchor) return
    const rect = anchor.getBoundingClientRect()
    const width = popup.getBoundingClientRect().width || 260
    const height = popup.getBoundingClientRect().height || 120
    const top = Math.max(8, Math.min(rect.top, window.innerHeight - height - 8))
    popup.style.left = `${Math.max(8, rect.left - width - 12)}px`
    popup.style.top = `${top}px`
    popup.style.setProperty('--em-intro-arrow-top', `${Math.max(12, Math.min(height - 12, rect.top + rect.height / 2 - top))}px`)
  }
  function showIntro() {
    if (dismissed || !anchor || popup) return
    popup = document.createElement('section')
    popup.className = 'em-tab-intro'
    popup.setAttribute('role', 'dialog')
    popup.setAttribute('aria-label', 'EM analysis is available')
    popup.innerHTML = '<strong>EM Analysis is now available</strong><p>Use this tab to analyze your nanoparticles. It stays available while this design contains nanoparticles.</p><button type="button" class="btn btn--primary">OK</button>'
    const dismiss = () => {
      dismissed = true
      try { storage?.setItem(INTRO_KEY, 'dismissed') } catch {}
      hideIntro()
      anchor.focus()
    }
    popup.querySelector('button').onclick = dismiss
    popup.addEventListener('keydown', event => { event.stopPropagation(); if (event.key === 'Escape') dismiss() })
    document.body.append(popup)
    position()
  }
  function apply(hasParticles) {
    rightSidebar?.setEMAvailable?.(hasParticles)
    if (hasParticles && previous === false) showIntro()
    if (!hasParticles) hideIntro()
    previous = hasParticles
  }
  function sync(state) {
    const current = state.assemblyActive ? `assembly:${state.currentAssembly?.id}` : `part:${state.currentDesign?.id}`
    const token = ++generation
    if (current !== context) {
      context = current
      previous = null
      hideIntro()
      rightSidebar?.setEMAvailable?.(false)
    }
    if (!state.assemblyActive) { apply(!!state.currentDesign?.nanoparticles?.length); return }
    const instances = state.currentAssembly?.instances ?? []
    const designs = instances.map(instance => instance.source?.design)
    if (designs.some(design => design?.nanoparticles?.length)) { apply(true); return }
    const missing = instances.filter((_, index) => !designs[index])
    if (!missing.length) { apply(false); return }
    // The shared API cache deduplicates reads of repeated part sources and
    // invalidates updated revisions. Do not infer absence from a loading renderer.
    Promise.all(missing.map(instance => api?.getInstanceDesign?.(instance.id)))
      .then(results => {
        if (token !== generation) return
        if (results.some(result => result?.design?.nanoparticles?.length)) apply(true)
        else if (results.every(result => result?.design)) apply(false)
      }).catch(() => { /* An unresolved source is not proof of particle removal. */ })
  }
  const unsubscribe = store.subscribe?.((state, old) => {
    if (state.currentDesign !== old.currentDesign || state.currentAssembly !== old.currentAssembly || state.assemblyActive !== old.assemblyActive) sync(state)
  })
  sync(store.getState())
  const unsubscribeSidebar = rightSidebar?.onChange?.(position)
  window.addEventListener('resize', position)
  window.addEventListener('scroll', position, true)
  const observer = typeof window.ResizeObserver === 'function' ? new window.ResizeObserver(position) : null
  if (anchor) observer?.observe(anchor)
  return { dispose() { generation++; unsubscribe?.(); unsubscribeSidebar?.(); hideIntro(); observer?.disconnect(); window.removeEventListener('resize', position); window.removeEventListener('scroll', position, true) } }
}
