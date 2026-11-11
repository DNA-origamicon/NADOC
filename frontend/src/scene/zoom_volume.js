import { PRESENTATION_EVENT } from './presentation_checkpoint_animation.js'
import './zoom_volume.css'
import * as THREE from 'three'
import { initZoomVolumeEntry } from './zoom_volume_entry.js'
import { boxIcon, eyeIcon, powerIcon } from './volume_panel.js'
import { getSectionCollapsed, setSectionCollapsed } from '../ui/section_collapse_state.js'
export { fitZoomCamera, zoomSelectionSource } from './zoom_volume_entry.js'

/** Each entry owns its selection, render requests, inset and teardown. */
export function initZoomVolume(deps) {
  const { document, store } = deps
  const pane = document.getElementById('right-tab-content-visualization')
  if (!pane) return null
  const section = document.createElement('div')
  section.id = 'zoom-volume-section'; section.className = 'panel-section ox-card'
  section.innerHTML = `<h2 class="volume-panel-heading"><button id="zoom-volume-heading" type="button" style="all:unset;cursor:pointer"><span class="section-arrow">▼</span> Zoom Volumes</button><span class="volume-panel-actions">
    <button id="zoom-volume-enable-all" type="button">${powerIcon}</button>
    <button id="zoom-volume-toggle-all" type="button">${eyeIcon}</button>
    <button id="zoom-volume-add" type="button" title="Add zoom volume from current selection" aria-label="Add zoom volume from current selection">${boxIcon}</button>
  </span></h2><div id="zoom-volume-body"><div id="zoom-volume-list" class="volume-entry-list"></div><div id="zoom-volume-status" role="status">Select entities, then add a zoom volume.</div></div>`
  pane.append(section)
  const $ = key => section.querySelector(`#zoom-volume-${key}`)
  const entries = new Map()
  let nextId = 0, disposed = false, renderer = null, boxEntryId = null
  // One WebGL context for the entire list; per-entry canvases retain each image.
  function getInsetRenderer() {
    if (!renderer) {
      renderer = new THREE.WebGLRenderer({ antialias: true })
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
      renderer.setClearColor(0x171e28)
    }
    return renderer
  }
  let collapsed = getSectionCollapsed('visualization', section.id, false)
  function collapse() {
    $('body').hidden = collapsed
    $('heading').setAttribute('aria-expanded', String(!collapsed))
    $('heading').querySelector('.section-arrow').classList.toggle('is-collapsed', collapsed)
  }
  $('heading').onclick = () => { collapsed = !collapsed; collapse(); setSectionCollapsed('visualization', section.id, collapsed) }
  collapse()
  function updateVisibility() {
    for (const [control, key, noun] of [['enable-all', 'enabled', 'insets'], ['toggle-all', 'box', 'volume outlines']]) {
      const button = $(control), all = entries.size > 0 && [...entries.values()].every(entry => entry.visibility(key))
      button.setAttribute('aria-pressed', String(all)); button.disabled = !entries.size
      button.title = `${all ? 'Hide' : 'Show'} all ${noun}`; button.setAttribute('aria-label', button.title)
    }
  }
  function remove(id) { entries.get(id)?.dispose(); entries.delete(id); if (boxEntryId === id) boxEntryId = null; updateVisibility() }
  function clear() { for (const id of entries.keys()) remove(id) }
  function addEntry(initialize, name = null) {
    if (disposed) return null
    const number = ++nextId, id = `zoom-${crypto.randomUUID()}`
    const entry = initZoomVolumeEntry({ ...deps, getInsetRenderer, parent: $('list'), id, name: name ?? `Zoom Volume ${number}`,
      position: ['tr', 'tl', 'br', 'bl'][(number - 1) % 4], onDelete: () => remove(id), onVisibilityChange: updateVisibility })
    if (!initialize(entry)) { entry.dispose(); $('status').textContent = 'Select an element first.'; return null }
    entries.set(id, entry); updateVisibility(); $('status').textContent = ''
    return id
  }
  function capture() { return addEntry(entry => entry.capture()) }
  function setBox(value) {
    if (disposed) return false
    if (boxEntryId && entries.has(boxEntryId)) return entries.get(boxEntryId).setBox(value)
    boxEntryId = addEntry(entry => entry.setBox(value), 'Submodel box')
    return boxEntryId !== null
  }
  const onPresentation = ({ detail }) => {
    const state = store.getState(), doc = state[state.assemblyActive ? 'currentAssembly' : 'currentDesign']
    const ids = detail?.documentId === doc?.id ? detail.zoomVolumeIds : null
    for (const [id, entry] of entries) entry.setPresentationVisible(Array.isArray(ids) ? ids.includes(id) : null)
  }
  window.addEventListener(PRESENTATION_EVENT, onPresentation)
  const onBox = event => setBox(event.detail)
  window.addEventListener('nadoc:zoom-volume-box', onBox)
  $('add').onclick = capture
  for (const [control, key] of [['enable-all', 'enabled'], ['toggle-all', 'box']]) $(control).onclick = () => {
    const visible = ![...entries.values()].every(entry => entry.visibility(key))
    for (const entry of entries.values()) entry.setVisibility(key, visible)
    updateVisibility()
  }
  updateVisibility()
  deps.assemblyRenderer?.onRebuildComplete?.(() => { if (!disposed) for (const entry of entries.values()) entry.refreshAssembly() })
  const unsubscribe = store.subscribe((n, p) => {
    if (n.assemblyActive !== p.assemblyActive || (n.assemblyActive ? n.currentAssembly?.id !== p.currentAssembly?.id : n.currentDesign?.id !== p.currentDesign?.id)) clear()
  })
  return { capture, setBox, clear, remove,
    list: () => [...entries].map(([id, entry]) => ({ id, name: entry.name(), visible: entry.visibility('enabled') })),
    debugAtoms: () => [...entries.values()].flatMap(entry => entry.debugAtoms()),
    debug: () => ({ ...([ ...entries.values()].at(-1)?.debug() ?? {}), entries: [...entries].map(([id, entry]) => ({ id, ...entry.debug() })) }),
    dispose() { disposed = true; window.removeEventListener(PRESENTATION_EVENT, onPresentation); window.removeEventListener('nadoc:zoom-volume-box', onBox); clear(); unsubscribe(); renderer?.dispose(); renderer?.forceContextLoss(); section.remove() },
  }
}
