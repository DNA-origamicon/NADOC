/**
 * Right-sidebar "Annotations" tab: a scrollable list of annotation entries.
 * Each entry edits one annotation through the shared controller; the overlay
 * (scene/annotation_overlay.js) renders it. Structural changes re-render the
 * list; value edits update in place so typing never loses focus.
 */
import './annotation_panel.css'
import { ANNOTATION_ICONS, annotationIconMarkup } from '../scene/annotation_icons.js'
import {
  CALLOUT_TYPES, SIZE_RANGE, TRANSPARENCY_RANGE, annotationHasContent, MAX_TEXT_LENGTH,
} from '../scene/annotation_model.js'
import { describeTarget } from '../scene/annotation_targets.js'
import { icon } from './primitives/icon.js'

const POPOVER_MARGIN = 8
const POPOVER_FALLBACK = { w: 208, h: 96 }

function h(document, tag, className, props = {}) {
  const node = document.createElement(tag)
  if (className) node.className = className
  for (const [key, value] of Object.entries(props)) {
    if (key === 'text') node.textContent = value
    else if (key === 'dataset') Object.assign(node.dataset, value)
    else if (key in node) node[key] = value
    else node.setAttribute(key, value)
  }
  return node
}

export function initAnnotationPanel({ document = globalThis.document, root, controller, store, getDesign = () => null }) {
  if (!root) return null
  root.replaceChildren()
  const panel = h(document, 'div', 'anno-panel')
  const head = h(document, 'div', 'anno-head')
  const title = h(document, 'h2', '', { text: 'Annotations' })
  const count = h(document, 'span', 'anno-count')
  const addBtn = h(document, 'button', 'anno-add', { type: 'button', text: '+ Add', title: 'Add an annotation' })
  head.append(title, count, addBtn)
  const enableRow = h(document, 'label', 'anno-enable')
  const enableBox = h(document, 'input', '', { type: 'checkbox' })
  enableBox.dataset.field = 'enabled'
  enableRow.append(enableBox, h(document, 'span', '', { text: 'Show annotations in the viewport' }))
  const disabledNote = h(document, 'p', 'anno-note', { text: 'All annotations are hidden. Entries below are kept and saved with the file.', hidden: true })
  const hint = h(document, 'p', 'anno-hint', {
    text: 'Select a base, end, domain, strand, cluster… in the viewport, then press “Use selection” on an entry. A callout appears once it has text or an icon.',
  })
  const list = h(document, 'div', 'anno-list', { role: 'list' })
  const unavailable = h(document, 'p', 'anno-note anno-unavailable', {
    text: 'Annotations are available while editing a part.', hidden: true,
  })
  panel.append(head, enableRow, disabledNote, hint, list, unavailable)
  root.append(panel)

  const cards = new Map()
  let popover = null
  let available = true

  const selectionItems = () => {
    const sel = store?.getState?.().selection
    return sel?.context === 'design' || sel?.context == null ? (sel?.items ?? []) : []
  }

  // ── icon popup ────────────────────────────────────────────────────────
  /** Fixed-position the popup under (or above) its button, kept fully on screen. */
  function placePopover(node, anchor) {
    const r = anchor.getBoundingClientRect()
    const view = document.defaultView
    const vw = view?.innerWidth || 1e4, vh = view?.innerHeight || 1e4
    const width = node.offsetWidth || POPOVER_FALLBACK.w, height = node.offsetHeight || POPOVER_FALLBACK.h
    const left = Math.min(Math.max(POPOVER_MARGIN, r.left), Math.max(POPOVER_MARGIN, vw - width - POPOVER_MARGIN))
    const below = r.bottom + 4
    const top = below + height + POPOVER_MARGIN > vh ? Math.max(POPOVER_MARGIN, r.top - height - 4) : below
    node.style.left = `${left}px`
    node.style.top = `${top}px`
  }
  function closePopover() {
    if (!popover) return
    popover.node.remove()
    document.removeEventListener('pointerdown', popover.outside, true)
    document.removeEventListener('keydown', popover.key, true)
    popover = null
  }
  function openPopover(entryId, anchor) {
    closePopover()
    const current = controller.get(entryId)?.icon ?? null
    const node = h(document, 'div', 'anno-icon-pop', { role: 'dialog', 'aria-label': 'Choose icon' })
    const choose = key => { controller.update(entryId, { icon: key }); refreshIconButton(entryId); closePopover() }
    for (const item of ANNOTATION_ICONS) {
      const b = h(document, 'button', item.key === current ? 'is-selected' : '', { type: 'button', title: item.label, 'aria-label': item.label })
      b.innerHTML = annotationIconMarkup(item.key, 22)
      b.addEventListener('click', () => choose(item.key))
      node.append(b)
    }
    const none = h(document, 'button', `anno-icon-none${current ? '' : ' is-selected'}`, { type: 'button', text: 'None', title: 'No icon' })
    none.addEventListener('click', () => choose(null))
    node.append(none)
    root.append(node)
    placePopover(node, anchor)
    const outside = event => { if (!node.contains(event.target) && !anchor.contains(event.target)) closePopover() }
    const key = event => { if (event.key === 'Escape') { event.stopPropagation(); closePopover() } }
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('keydown', key, true)
    popover = { node, outside, key }
  }

  // ── entry cards ───────────────────────────────────────────────────────
  function refreshIconButton(id) {
    const card = cards.get(id)
    const entry = controller.get(id)
    if (!card || !entry) return
    card.iconBtn.replaceChildren()
    if (entry.icon) {
      const holder = h(document, 'span')
      holder.innerHTML = annotationIconMarkup(entry.icon, 18)
      card.iconBtn.append(holder, h(document, 'span', '', { text: ANNOTATION_ICONS.find(i => i.key === entry.icon)?.label ?? '' }))
    } else card.iconBtn.append(h(document, 'span', '', { text: 'Choose icon…' }))
    refreshWarning(id)
  }
  function refreshWarning(id) {
    const card = cards.get(id)
    const entry = controller.get(id)
    if (!card || !entry) return
    card.warn.hidden = annotationHasContent(entry)
  }
  function refreshTarget(id) {
    const card = cards.get(id)
    const entry = controller.get(id)
    if (!card || !entry) return
    const label = describeTarget(entry.refs, getDesign())
    card.target.textContent = label
    card.target.title = label
    card.target.classList.toggle('is-empty', !entry.refs.length)
    card.clear.hidden = !entry.refs.length
    card.use.disabled = !selectionItems().length
    card.use.title = selectionItems().length
      ? `Attach the ${selectionItems().length} selected item${selectionItems().length > 1 ? 's' : ''}`
      : 'Select something in the viewport first'
  }

  function rangeRow(label, range, value, format, onInput, testId) {
    const row = h(document, 'div', 'anno-row')
    const lab = h(document, 'label', '', { text: label })
    const input = h(document, 'input', '', { type: 'range', min: range.min, max: range.max, step: range.step, value })
    input.dataset.field = testId
    const out = h(document, 'output', '', { text: format(value) })
    input.addEventListener('input', () => { const n = Number(input.value); out.textContent = format(n); onInput(n) })
    row.append(lab, input, out)
    return row
  }

  function buildCard(entry) {
    const id = entry.id
    const card = h(document, 'div', 'anno-card', { role: 'listitem', dataset: { annotationId: id } })
    card.style.setProperty('--anno-color', entry.color)

    const text = h(document, 'textarea', 'anno-text', {
      placeholder: 'Callout text…', rows: 2, maxLength: MAX_TEXT_LENGTH, value: entry.text,
    })
    text.dataset.field = 'text'
    text.addEventListener('input', () => { controller.update(id, { text: text.value }); refreshWarning(id) })

    const eye = h(document, 'button', 'anno-icon-btn-small', { type: 'button', title: 'Show / hide this callout' })
    const paintEye = visible => { eye.replaceChildren(icon(visible ? 'eye' : 'eye-off', { size: 14 })); card.classList.toggle('is-hidden-entry', !visible) }
    paintEye(entry.visible)
    eye.dataset.field = 'visible'
    eye.addEventListener('click', () => { const next = !controller.get(id).visible; controller.update(id, { visible: next }); paintEye(next) })
    const del = h(document, 'button', 'anno-icon-btn-small', { type: 'button', title: 'Delete annotation' })
    del.append(icon('trash', { size: 14 }))
    del.dataset.field = 'delete'
    del.addEventListener('click', () => { closePopover(); controller.remove(id) })
    const topRow = h(document, 'div', 'anno-row')
    const actions = h(document, 'div', 'anno-actions')
    actions.append(eye, del)
    topRow.append(h(document, 'span', 'anno-count', { text: 'Text' }), actions)

    const iconBtn = h(document, 'button', 'anno-icon-btn', { type: 'button', title: 'Choose an icon' })
    iconBtn.dataset.field = 'icon'
    iconBtn.addEventListener('click', () => (popover ? closePopover() : openPopover(id, iconBtn)))
    const iconRow = h(document, 'div', 'anno-row')
    iconRow.append(h(document, 'label', '', { text: 'Icon' }), iconBtn)

    const type = h(document, 'select', '')
    type.dataset.field = 'calloutType'
    for (const t of CALLOUT_TYPES) type.append(h(document, 'option', '', { value: t.key, text: t.label, selected: t.key === entry.calloutType }))
    type.addEventListener('change', () => controller.update(id, { calloutType: type.value }))
    const typeRow = h(document, 'div', 'anno-row')
    typeRow.append(h(document, 'label', '', { text: 'Callout' }), type)

    const color = h(document, 'input', '', { type: 'color', value: entry.color })
    color.dataset.field = 'color'
    color.addEventListener('input', () => { card.style.setProperty('--anno-color', color.value); controller.update(id, { color: color.value }) })
    const colorRow = h(document, 'div', 'anno-row')
    colorRow.append(h(document, 'label', '', { text: 'Color' }), color)

    const transparency = rangeRow('Transparency', TRANSPARENCY_RANGE, entry.transparency,
      v => `${Math.round(v * 100)}%`, v => controller.update(id, { transparency: v }), 'transparency')
    const size = rangeRow('Size', SIZE_RANGE, entry.size, v => `${v.toFixed(2)}×`, v => controller.update(id, { size: v }), 'size')

    const manual = h(document, 'input', '', { type: 'checkbox', checked: entry.manual })
    manual.dataset.field = 'manual'
    const manualLabel = h(document, 'label', '', { text: 'Manual position' })
    manualLabel.style.cssText = 'display:flex;align-items:center;gap:6px;min-width:0;color:inherit'
    manualLabel.prepend(manual)
    const manualHint = h(document, 'span', 'anno-note', { text: entry.manual ? 'Drag the ◢ corner in the viewport.' : 'Follows the target.' })
    manual.addEventListener('change', () => {
      controller.update(id, { manual: manual.checked })
      manualHint.textContent = manual.checked ? 'Drag the ◢ corner in the viewport.' : 'Follows the target.'
    })
    const manualRow = h(document, 'div', 'anno-row')
    manualRow.append(manualLabel)

    const target = h(document, 'span', 'anno-target')
    const use = h(document, 'button', 'anno-use-selection', { type: 'button', text: 'Use selection' })
    use.dataset.field = 'useSelection'
    use.addEventListener('click', () => {
      const items = selectionItems()
      if (items.length) controller.update(id, { refs: items })
    })
    const clear = h(document, 'button', 'anno-icon-btn-small', { type: 'button', title: 'Clear target' })
    clear.append(icon('x', { size: 12 }))
    clear.dataset.field = 'clearTarget'
    clear.addEventListener('click', () => controller.update(id, { refs: [] }))
    const targetRow = h(document, 'div', 'anno-row')
    const spacer = h(document, 'span', 'anno-grow')
    targetRow.append(h(document, 'label', '', { text: 'Target' }), spacer, clear, use)

    const warn = h(document, 'p', 'anno-warn', { text: 'Add text or pick an icon — the callout won’t appear until you do.' })

    card.append(topRow, text, iconRow, typeRow, colorRow, transparency, size, manualRow, manualHint, targetRow, target, warn)
    cards.set(id, { card, iconBtn, warn, target, clear, use, text })
    refreshIconButton(id)
    refreshTarget(id)
    return card
  }

  function syncEnabled() {
    enableBox.checked = controller.isEnabled()
    disabledNote.hidden = controller.isEnabled() || !available
    list.classList.toggle('is-globally-off', !controller.isEnabled())
  }
  enableBox.addEventListener('change', () => controller.setEnabled(enableBox.checked))

  function renderList({ focusId = null } = {}) {
    closePopover()
    const scroll = list.scrollTop
    cards.clear()
    const entries = controller.list()
    list.replaceChildren()
    if (!entries.length) list.append(h(document, 'div', 'anno-empty', { text: 'No annotations yet.' }))
    for (const entry of entries) list.append(buildCard(entry))
    count.textContent = entries.length ? `${entries.length}` : ''
    syncEnabled()
    list.scrollTop = scroll
    if (focusId) {
      cards.get(focusId)?.card.scrollIntoView?.({ block: 'nearest' })
      cards.get(focusId)?.text.focus?.()
    }
  }

  list.addEventListener('scroll', closePopover)
  addBtn.addEventListener('click', () => { controller.add() })
  const off = controller.subscribe(event => {
    if (event.type === 'add') renderList({ focusId: event.id })
    else if (event.type === 'enabled') syncEnabled()
    else if (event.structural) renderList()
  })

  const refreshAll = () => { for (const id of cards.keys()) refreshTarget(id) }
  const unsubscribeStore = store?.subscribe?.((state, prev) => {
    if (state.selection !== prev?.selection || state.currentDesign !== prev?.currentDesign) refreshAll()
  })

  renderList()

  return {
    setAvailable(next) {
      available = !!next
      list.hidden = head.hidden = hint.hidden = enableRow.hidden = !available
      unavailable.hidden = available
      syncEnabled()
      if (!available) closePopover()
    },
    isAvailable: () => available,
    refresh: renderList,
    dispose() { closePopover(); off(); unsubscribeStore?.(); root.replaceChildren() },
  }
}
