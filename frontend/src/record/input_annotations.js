// The overlay lives in the source tab, so it appears in both the capture preview
// and the saved media without transmitting keyboard input between tabs.
export function inputLabel(event) {
  const target = event.composedPath?.()[0] || event.target
  const editing = target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')
  if (event.type === 'keydown' && (editing || event.repeat || event.isComposing)) return ''
  const modifiers = [['ctrlKey', 'Ctrl'], ['altKey', 'Alt'], ['shiftKey', 'Shift'], ['metaKey', 'Meta']]
    .filter(([property]) => event[property]).map(([, name]) => name)
  let key
  if (event.type === 'pointerdown') {
    if (event.pointerType && event.pointerType !== 'mouse') return ''
    key = ['Left click', 'Middle click', 'Right click', 'Back click', 'Forward click'][event.button]
  } else {
    key = ({ ' ': 'Space', ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Control: 'Ctrl' })[event.key] || event.key
    if (key?.length === 1) key = key.toUpperCase()
    if (['Dead', 'Unidentified', 'Process'].includes(key)) return ''
  }
  if (!key) return ''
  if (!modifiers.includes(key)) modifiers.push(key)
  return modifiers.join(' + ')
}

export function createInputAnnotations(doc = document) {
  let host, root, list
  const timers = new Set()
  const later = (fn, delay) => {
    const timer = setTimeout(() => { timers.delete(timer); fn() }, delay)
    timers.add(timer)
  }
  function show(event) {
    const label = inputLabel(event)
    if (!label) return
    const entry = doc.createElement('div')
    entry.className = 'key'; entry.textContent = label
    list.append(entry)
    while (list.children.length > 4) list.firstChild.remove()
    later(() => entry.remove(), 2200)
    if (event.type === 'pointerdown') {
      const ring = doc.createElement('div')
      ring.className = 'click'
      ring.style.left = `${event.clientX}px`; ring.style.top = `${event.clientY}px`
      root.append(ring)
      later(() => ring.remove(), 650)
    }
  }
  function clear() {
    timers.forEach(clearTimeout); timers.clear()
    list?.replaceChildren()
    root?.querySelectorAll('.click').forEach(el => el.remove())
  }
  function disable() {
    doc.removeEventListener('keydown', show, true)
    doc.removeEventListener('pointerdown', show, true)
    doc.defaultView.removeEventListener('blur', clear)
    clear(); host?.remove(); host = null
  }
  return {
    setEnabled(enabled) {
      if (!enabled) { disable(); return }
      if (host) return
      host = doc.createElement('div')
      host.dataset.nadocInputAnnotations = ''
      host.setAttribute('aria-hidden', 'true')
      host.style.cssText = 'all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483647;'
      root = host.attachShadow({ mode: 'open' })
      root.innerHTML = `<style>
        :host { pointer-events:none !important; }
        .keys { position:absolute; bottom:24px; left:24px; display:flex; flex-direction:column; align-items:flex-start; gap:7px; }
        .key { background:rgba(13,17,23,.92); color:#fff; border:1px solid #8ba4c0; border-radius:7px; padding:9px 15px; font:600 18px/1.4 system-ui,sans-serif; box-shadow:0 2px 8px #0008; }
        .click { position:absolute; width:36px; height:36px; transform:translate(-50%,-50%); border:3px solid #ffd866; background:#ffd86633; border-radius:50%; box-sizing:border-box; }
      </style><div class="keys"></div>`
      list = root.querySelector('.keys')
      doc.body.append(host)
      // Capture phase also sees shortcuts handled by menus and the 3D viewer.
      doc.addEventListener('keydown', show, true)
      doc.addEventListener('pointerdown', show, true)
      doc.defaultView.addEventListener('blur', clear)
    },
    dispose: disable,
  }
}
