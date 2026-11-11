/** A second-document view of controls owned exclusively by the originating editor.
 * Keep the live tree in its document: existing ID lookups and delegated handlers
 * continue to work. No store, API client, broadcast channel or editor runs here.
 */
let serial = 0
export function mountDetachedControlView(source, host, { enabled = () => true, preserveIds = false } = {}) {
  const prefix = `detached-${++serial}-`
  const doc = source.ownerDocument
  const owner = doc.defaultView
  const remote = host.ownerDocument.defaultView
  const requestFrame = remote.requestAnimationFrame.bind(remote)
  const cancelFrame = remote.cancelAnimationFrame.bind(remote)
  const copies = new Map(), originals = new WeakMap()
  let disposed = false, frame
  function properties(original, copy) {
    if ('value' in original && original.type !== 'file' && copy.value !== original.value) copy.value = original.value
    for (const key of ['checked', 'indeterminate', 'selectedIndex']) if (key in original) copy[key] = original[key]
    if (original.tagName === 'CANVAS' && original.width && original.height) {
      try { copy.getContext('2d')?.drawImage(original, 0, 0) } catch { /* Not yet drawn. */ }
    }
  }
  function attributes(original, copy) {
    for (const attr of [...copy.attributes]) if (!original.hasAttribute(attr.name)) copy.removeAttribute(attr.name)
    for (const attr of original.attributes) if (copy.getAttribute(attr.name) !== attr.value) copy.setAttribute(attr.name, attr.value)
    if (!preserveIds) {
      if (original.id) { copy.id = prefix + original.id; copy.dataset.sidebarSourceId = original.id }
      for (const attr of ['for', 'aria-controls', 'aria-labelledby', 'aria-describedby', 'list']) {
        if (original.hasAttribute(attr)) copy.setAttribute(attr, original.getAttribute(attr).split(/\s+/).map(id =>
          source.contains(doc.getElementById(id)) ? prefix + id : id).join(' '))
      }
      if (original.tagName === 'INPUT' && original.name) copy.name = prefix + original.name
    }
    // A parked canonical pane still needs to be visible in its remote column.
    if (original === source) copy.hidden = false
  }
  function clone(original) {
    const copy = original.cloneNode(false)
    copies.set(original, copy); originals.set(copy, original)
    if (original.nodeType === 1) attributes(original, copy)
    for (const child of original.childNodes) copy.append(clone(child))
    if (original.nodeType === 1) properties(original, copy)
    return copy
  }
  function children(original) {
    const copy = copies.get(original)
    if (!copy) return
    const wanted = new Set()
    let previous = null
    for (const child of original.childNodes) {
      const target = copies.get(child) || clone(child)
      wanted.add(target)
      const before = previous ? previous.nextSibling : copy.firstChild
      if (before !== target) copy.insertBefore(target, before)
      previous = target
    }
    for (const child of [...copy.childNodes]) if (!wanted.has(child)) child.remove()
  }
  function apply(records) {
    for (const record of records) {
      const copy = copies.get(record.target)
      if (!copy) continue
      if (record.type === 'attributes') attributes(record.target, copy)
      else if (record.type === 'characterData') copy.nodeValue = record.target.nodeValue
      else children(record.target)
    }
    for (const [original] of copies) if (original !== source && !source.contains(original)) copies.delete(original)
  }
  const observer = new owner.MutationObserver(apply)
  host.replaceChildren(clone(source))
  observer.observe(source, { subtree: true, childList: true, attributes: true, characterData: true })
  function flush() {
    apply(observer.takeRecords())
    for (const original of source.querySelectorAll('input, select, textarea, canvas')) {
      const copy = copies.get(original)
      if (copy) properties(original, copy)
    }
  }
  function tick() {
    if (disposed) return
    flush(); frame = requestFrame(tick)
  }
  // Forward events to the actual nodes, never resolve another window by name or
  // document ID. Native editing stays in the remote control before input/change.
  function forward(event) {
    if (!enabled()) { event.preventDefault(); return }
    const original = originals.get(event.target)
    if (!original || !source.contains(original)) return
    const type = event.type
    if (original.closest?.(':disabled, [aria-disabled="true"], [inert]')) { event.preventDefault(); return }
    if (type === 'focusin') { original.focus?.({ preventScroll: true }); return }
    if (type === 'focusout') { original.blur?.(); return }
    if (['input', 'change'].includes(type)) {
      if (original.type === 'file') original.files = event.target.files
      else if ('value' in original) original.value = event.target.value
      if ('checked' in original) original.checked = event.target.checked
      if (typeof event.target.selectionStart === 'number') original.setSelectionRange?.(
        event.target.selectionStart, event.target.selectionEnd, event.target.selectionDirection)
    }
    // Restore a checkbox's pre-click state before native activation in the owner.
    const checkable = original.matches?.('input[type="checkbox"], input[type="radio"]')
    if (type === 'click' && original.matches?.('input[type="checkbox"]')) {
      original.checked = !event.target.checked
    }
    if (type === 'click' && original.matches?.('input[type="file"], select, option, label')) return
    const init = { bubbles: event.bubbles, cancelable: true, composed: true,
      key: event.key, code: event.code, repeat: event.repeat,
      ctrlKey: event.ctrlKey, shiftKey: event.shiftKey, altKey: event.altKey, metaKey: event.metaKey,
      button: event.button, buttons: event.buttons, detail: event.detail,
      clientX: event.clientX, clientY: event.clientY,
      pointerId: event.pointerId, pointerType: event.pointerType, isPrimary: event.isPrimary,
      dataTransfer: event.dataTransfer, inputType: event.inputType, data: event.data }
    const Constructor = type.startsWith('key') ? owner.KeyboardEvent
      : type.startsWith('pointer') ? owner.PointerEvent
        : ['click', 'dblclick', 'contextmenu', 'mousedown', 'mouseup', 'mousemove'].includes(type) ? owner.MouseEvent
          : type.startsWith('drag') || type === 'drop' ? owner.DragEvent : owner.Event
    const previousFocus = doc.activeElement
    const forwarded = new (Constructor || owner.Event)(type, init)
    // Pointer capture and coordinates belong to the window of the gesture.
    // Adapt the target/ancestor nodes for this synchronous dispatch only.
    const restore = []
    for (let node = original; node && source.contains(node); node = node.parentElement) {
      const copy = copies.get(node)
      if (!copy || node.nodeType !== 1) continue
      for (const method of ['getBoundingClientRect', 'setPointerCapture', 'releasePointerCapture', 'hasPointerCapture']) {
        if (typeof copy[method] !== 'function') continue
        const own = Object.getOwnPropertyDescriptor(node, method)
        Object.defineProperty(node, method, { configurable: true, value: (...args) => copy[method](...args) })
        restore.push(() => { if (own) Object.defineProperty(node, method, own); else delete node[method] })
      }
    }
    try { if (!original.dispatchEvent(forwarded)) event.preventDefault() }
    finally { for (const reset of restore.reverse()) reset() }
    if (type === 'contextmenu' || type === 'submit' ||
        (type === 'click' && (checkable || original.closest?.('button, a')))) event.preventDefault()
    // The owner already performed native activation. Suppress a second remote
    // input/change or form submission, then restore pixels after click rollback.
    if (type === 'click' && checkable) queueMicrotask(() => { if (!disposed) flush() })
    // Preserve auto-focus from controllers that reveal an editor on click.
    flush()
    const focused = copies.get(doc.activeElement)
    if (focused && doc.activeElement !== previousFocus && host.ownerDocument.activeElement !== focused) focused.focus?.({ preventScroll: true })
  }
  const events = ['click', 'dblclick', 'contextmenu', 'input', 'change', 'keydown', 'keyup',
    'focusin', 'focusout', 'pointerdown', 'pointerup', 'pointercancel', 'lostpointercapture', 'pointermove', 'pointerover', 'pointerout', 'pointerenter', 'pointerleave',
    'mousedown', 'mouseup', 'mousemove', 'dragstart', 'dragover', 'dragend', 'drop', 'submit']
  for (const type of events) host.addEventListener(type, forward, true)
  frame = requestFrame(tick)
  return { flush, dispose() {
    disposed = true; observer.disconnect(); cancelFrame(frame)
    for (const type of events) host.removeEventListener(type, forward, true)
    copies.clear(); host.replaceChildren()
  } }
}
