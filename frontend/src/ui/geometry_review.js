/** Help → geometry Review. Private scenes and evidence, independent of the open design. */
import { geometryReviewCases } from './geometry_review_catalog.js'
import './geometry_review.css'

export function initGeometryReview({
  cases = geometryReviewCases,
  loadRenderer = () => import('./geometry_review_content.js'),
} = {}) {
  const menu = document.getElementById('menu-help-geometry-review')
  const modal = document.createElement('dialog')
  modal.id = 'geometry-review'
  modal.className = 'geometry-review'
  modal.setAttribute('aria-labelledby', 'geometry-review-title')
  modal.innerHTML = `<header class="gr-header">
    <h1 id="geometry-review-title">geometry Review</h1>
    <label>Review case <select class="gr-case" aria-label="Review case"></select></label>
    <span>Read-only · independent of your open design</span>
    <button type="button" class="gr-close" autofocus>Close</button>
    </header><div class="gr-body" aria-live="polite"></div>`
  document.body.append(modal)
  const select = modal.querySelector('.gr-case'), body = modal.querySelector('.gr-body')
  for (const entry of cases) select.add(new Option(entry.title, entry.id))
  let content = null, generation = 0, controller = null, disposed = false
  const loaded = new Map()

  function release() {
    generation++
    content?.dispose()
    content = null
    body.replaceChildren()
    delete modal.dataset.ready
  }
  function close() {
    release()
    controller?.abort()
    controller = null
    loaded.clear()
    if (modal.open) modal.close()
    menu?.setAttribute('aria-expanded', 'false')
  }
  async function showCase() {
    release()
    const mine = generation
    const entry = cases.find(row => row.id === select.value)
    body.textContent = 'Loading prepared 3D evidence…'
    try {
      if (!entry) throw new Error('No geometry review cases are available.')
      if (!loaded.has(entry.load)) loaded.set(entry.load, entry.load({ signal: controller.signal }))
      const [rootBundle, renderer] = await Promise.all([loaded.get(entry.load), loadRenderer()])
      if (!modal.open || mine !== generation || disposed) return
      const bundle = entry.control ? rootBundle.controls[entry.control] : rootBundle
      body.replaceChildren()
      content = (entry.render ?? renderer.mountGeometryReview)(body, bundle)
      modal.dataset.case = entry.id
      modal.dataset.ready = 'true'
      body.scrollTop = 0
    } catch (error) {
      if (!modal.open || mine !== generation || disposed) return
      loaded.delete(entry?.load)
      release()
      const message = document.createElement('p')
      message.setAttribute('role', 'alert')
      message.textContent = error instanceof Error ? error.message : String(error)
      const retry = document.createElement('button')
      retry.textContent = 'Retry'
      retry.addEventListener('click', showCase)
      body.append(message, retry)
    }
  }
  function show() {
    if (disposed || modal.open) return
    controller = new AbortController()
    modal.showModal()
    menu?.setAttribute('aria-expanded', 'true')
    void showCase()
  }
  const cancel = event => { event.preventDefault(); close() }
  menu?.setAttribute('aria-haspopup', 'dialog')
  menu?.setAttribute('aria-expanded', 'false')
  menu?.addEventListener('click', show)
  select.addEventListener('change', showCase)
  modal.querySelector('.gr-close').addEventListener('click', close)
  modal.addEventListener('cancel', cancel)
  // A modal owns its shortcuts; app history/selection shortcuts must not run beneath it.
  modal.addEventListener('keydown', event => event.stopPropagation())
  return { show, close, element: modal,
    isRendered: () => !!content?.isRendered(),
    dispose() {
      if (disposed) return
      close()
      disposed = true
      menu?.removeEventListener('click', show)
      modal.remove()
    },
  }
}
