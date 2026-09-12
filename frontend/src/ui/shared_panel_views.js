/**
 * Multiple views of an existing, single-controller panel.
 *
 * The live DOM (and all its listeners) belongs to the view being used. Other
 * views mirror its structure, form properties and canvases. Moving the live
 * tree before interaction preserves the existing controller, native controls,
 * popup anchors and delegated handlers without registering actions twice.
 * Each host retains its own scroll position. Copies never have canonical IDs.
 */
export function sharedPanelSelector(selector) {
  // IDs inside attribute values (hrefs, inline color strings) are not selectors.
  let quote = null, attribute = false, result = ''
  for (let i = 0; i < selector.length; i++) {
    const c = selector[i]
    if (quote) {
      result += c
      if (c === quote && selector[i - 1] !== '\\') quote = null
    } else if (c === '"' || c === "'") { quote = c; result += c }
    else if (c === '[') { attribute = true; result += c }
    else if (c === ']') { attribute = false; result += c }
    else if (c === '#' && !attribute) {
      const match = selector.slice(i + 1).match(/^[a-zA-Z_][\w-]*/)
      if (match) {
        const id = match[0]
        result += `:is(#${id}, [data-sidebar-source-id="${id}"])`
        i += id.length
      } else result += c
    } else result += c
  }
  return result
}

export function enableSharedPanelStyles(doc = document) {
  function visit(rules) {
    for (const rule of rules) {
      if (rule.selectorText && !rule.selectorText.includes('data-sidebar-source-id')) {
        rule.selectorText = sharedPanelSelector(rule.selectorText)
      }
      if (rule.cssRules) visit(rule.cssRules)
    }
  }
  for (const sheet of doc.styleSheets) {
    try { visit(sheet.cssRules) } catch { /* Cross-origin sheets cannot be inspected. */ }
  }
}

function nodes(root) { return [root, ...root.querySelectorAll('*')] }
function scrolls(root) { return nodes(root).map(node => [node.scrollLeft, node.scrollTop]) }
function restoreScroll(root, saved) {
  nodes(root).forEach((node, i) => {
    if (saved[i]) { node.scrollLeft = saved[i][0]; node.scrollTop = saved[i][1] }
  })
}
function copyProperties(source, copy) {
  if ('value' in source && source.type !== 'file' && copy.value !== source.value) copy.value = source.value
  if (source.type === 'file' && source.files && copy.files !== source.files) copy.files = source.files
  if ('checked' in source) copy.checked = source.checked
  if ('indeterminate' in source) copy.indeterminate = source.indeterminate
  if (source.tagName === 'SELECT') copy.selectedIndex = source.selectedIndex
  if (source.tagName === 'CANVAS' && source.width && source.height) {
    try { copy.getContext('2d')?.drawImage(source, 0, 0, copy.width, copy.height) } catch { /* An uninitialized canvas has no frame yet. */ }
  }
}

export function createSharedPanelViews(source, parking) {
  const views = new Set()
  let active = null
  let pending = []
  let raf = null
  let serial = 0
  let disposed = false
  const observer = new MutationObserver(records => {
    // With no copies the next mount takes a fresh snapshot. Do not retain a
    // growing history of status updates (and detached nodes) in closed panels.
    if (views.size < 2) { pending = []; return }
    pending.push(...records); schedule()
  })
  observer.observe(source, { attributes: true, characterData: true, childList: true, subtree: true })

  function attributes(original, copy, view) {
    if (original.nodeType !== 1) return
    for (const attr of [...copy.attributes]) copy.removeAttribute(attr.name)
    for (const attr of original.attributes) copy.setAttribute(attr.name, attr.value)
    if (original.id) {
      copy.dataset.sidebarSourceId = original.id
      copy.id = `sidebar-copy-${view.id}-${original.id}`
    }
    if (original === source) { copy.hidden = false; copy.dataset.sidebarCopy = '' }
    for (const attr of ['for', 'aria-controls', 'aria-labelledby', 'aria-describedby', 'aria-owns', 'list']) {
      if (!copy.hasAttribute(attr)) continue
      copy.setAttribute(attr, copy.getAttribute(attr).split(/\s+/).map(id => {
        const target = document.getElementById(id)
        return target && source.contains(target) ? `sidebar-copy-${view.id}-${id}` : id
      }).join(' '))
    }
    const href = copy.getAttribute('href')
    if (href?.startsWith('#') && source.contains(document.getElementById(href.slice(1)))) {
      copy.setAttribute('href', `#sidebar-copy-${view.id}-${href.slice(1)}`)
    }
    if (copy.tagName === 'INPUT' && copy.name) copy.name = `sidebar-copy-${view.id}-${copy.name}`
  }
  function clone(original, view) {
    const copy = original.cloneNode(false)
    view.toSource.set(copy, original)
    view.fromSource.set(original, copy)
    attributes(original, copy, view)
    for (const child of original.childNodes) copy.append(clone(child, view))
    if (original.nodeType === 1) copyProperties(original, copy)
    return copy
  }
  function mirror(view) {
    const saved = view.root ? scrolls(view.root) : []
    view.toSource = new WeakMap()
    view.fromSource = new WeakMap()
    const copy = clone(source, view)
    view.host.replaceChildren(copy)
    view.root = copy
    restoreScroll(copy, saved)
  }
  function children(original, copy, view) {
    const wanted = new Set()
    let previous = null
    for (const child of original.childNodes) {
      const target = view.fromSource.get(child) || clone(child, view)
      wanted.add(target)
      const before = previous ? previous.nextSibling : copy.firstChild
      if (before !== target) copy.insertBefore(target, before)
      previous = target
    }
    for (const child of [...copy.childNodes]) if (!wanted.has(child)) child.remove()
  }
  function flush() {
    if (disposed) return
    const records = [...pending, ...observer.takeRecords()]
    pending = []
    const controls = source.querySelectorAll('input, select, textarea, canvas')
    for (const view of views) {
      if (view === active) continue
      if (!view.root) mirror(view)
      for (const record of records) {
        const original = record.target
        if (!source.contains(original)) continue
        const copy = view.fromSource.get(original)
        if (!copy) continue
        if (record.type === 'attributes') attributes(original, copy, view)
        else if (record.type === 'characterData') copy.nodeValue = original.nodeValue
        else if (record.type === 'childList') children(original, copy, view)
      }
      for (const original of controls) {
        const copy = view.fromSource.get(original)
        if (copy) copyProperties(original, copy)
      }
    }
  }
  function schedule() {
    if (raf !== null || disposed || views.size < 2) return
    raf = requestAnimationFrame(() => {
      raf = null
      flush()
      // checked/value and canvas pixels do not produce DOM mutations.
      schedule()
    })
  }

  function activate(view, target = null) {
    if (active === view) return target
    const mapped = target && view.toSource?.get(target)
    const original = mapped && source.contains(mapped) ? mapped : null
    const incomingScroll = view.root ? scrolls(view.root) : []
    const old = active
    // Mirror the outgoing live view BEFORE moving its tree, retaining its scroll.
    active = view
    if (old) mirror(old)
    view.host.replaceChildren(source)
    view.root = source
    source.hidden = false
    restoreScroll(source, incomingScroll)
    return original
  }

  function mount(host) {
    const view = { host, id: ++serial, root: null, pairs: [], toSource: null }
    views.add(view)
    if (!active) activate(view)
    else mirror(view)
    const hover = event => {
      const control = event.target.closest?.('input, button, select, textarea, a, canvas, summary, [tabindex], [draggable="true"]')
      if (!event.buttons && control && host.contains(control)) activate(view)
    }
    const focus = event => {
      if (active === view) return
      const target = activate(view, event.target)
      target?.focus?.({ preventScroll: true })
    }
    const click = event => {
      if (active === view) return
      // Keyboard/programmatic activation can arrive without a pointerover.
      const target = activate(view, event.target)
      event.preventDefault()
      event.stopImmediatePropagation()
      if (target) target.dispatchEvent(new MouseEvent(event.type, {
        bubbles: true, cancelable: true, clientX: event.clientX, clientY: event.clientY,
        button: event.button, ctrlKey: event.ctrlKey, shiftKey: event.shiftKey,
        altKey: event.altKey, metaKey: event.metaKey,
      }))
    }
    host.addEventListener('pointerover', hover, true)
    host.addEventListener('focusin', focus, true)
    host.addEventListener('click', click, true)
    host.addEventListener('contextmenu', click, true)
    schedule()
    return {
      activate: () => activate(view),
      dispose() {
        host.removeEventListener('pointerover', hover, true)
        host.removeEventListener('focusin', focus, true)
        host.removeEventListener('click', click, true)
        host.removeEventListener('contextmenu', click, true)
        views.delete(view)
        if (active === view) {
          active = null
          const next = [...views].at(-1)
          if (next) activate(next)
          else { parking.append(source); source.hidden = true }
        }
        host.replaceChildren()
        if (views.size < 2 && raf !== null) { cancelAnimationFrame(raf); raf = null }
      },
    }
  }
  return {
    mount, flush,
    dispose() { disposed = true; observer.disconnect(); if (raf !== null) cancelAnimationFrame(raf) },
  }
}
