import './animation_sidebar.css'

export function attachPoseThumbnail(anchor, pose) {
  if (!pose?.thumbnail?.match(/^data:image\/(jpeg|png|webp);base64,/)) return
  const doc = anchor.ownerDocument
  let popup = null, observer = null
  const hide = () => { popup?.remove(); popup = null; observer?.disconnect(); observer = null }
  const show = () => {
    hide()
    popup = doc.createElement('img')
    popup.className = 'pose-thumbnail'
    popup.alt = `Preview of ${pose.name}`
    popup.src = pose.thumbnail
    const rect = anchor.getBoundingClientRect()
    popup.style.left = `${Math.max(8, Math.min(rect.right + 8, doc.defaultView.innerWidth - 248))}px`
    popup.style.top = `${Math.max(8, Math.min(rect.top, doc.defaultView.innerHeight - 160))}px`
    doc.body.append(popup)
    observer = new MutationObserver(() => { if (!anchor.isConnected) hide() })
    observer.observe(doc.body, { childList: true, subtree: true })
  }
  anchor.addEventListener('pointerenter', show)
  anchor.addEventListener('pointerleave', hide)
  anchor.addEventListener('focus', show)
  anchor.addEventListener('blur', hide)
  anchor.addEventListener('click', hide)
}

/** Native selects do not expose option hover consistently; use a DOM listbox. */
export function enhancePoseSelect(select, poses) {
  const doc = select.ownerDocument
  let popup = null, outside = null, observer = null
  const close = () => {
    popup?.remove(); popup = null
    doc.removeEventListener('pointerdown', outside, true)
    observer?.disconnect(); observer = null
    select.setAttribute('aria-expanded', 'false')
  }
  const open = () => {
    close()
    popup = doc.createElement('div')
    popup.className = 'pose-options'
    popup.setAttribute('role', 'listbox')
    popup.setAttribute('aria-label', 'Camera poses')
    const rect = select.getBoundingClientRect()
    popup.style.left = `${rect.left}px`
    popup.style.top = `${Math.max(8, Math.min(rect.bottom, doc.defaultView.innerHeight - 240))}px`
    popup.style.minWidth = `${rect.width}px`
    for (const option of select.options) {
      const item = doc.createElement('button')
      item.className = 'btn btn--sm'
      item.type = 'button'; item.textContent = option.textContent
      item.setAttribute('role', 'option')
      item.setAttribute('aria-selected', String(select.value === option.value))
      attachPoseThumbnail(item, poses.find(p => p.id === option.value))
      item.addEventListener('click', () => {
        select.value = option.value
        close()
        select.dispatchEvent(new Event('change', { bubbles: true }))
        select.focus()
      })
      popup.append(item)
    }
    popup.addEventListener('keydown', event => {
      event.stopPropagation()
      if (event.key === 'Escape') { close(); select.focus() }
      if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
        event.preventDefault()
        const items = [...popup.children], i = items.indexOf(doc.activeElement)
        items[(i + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus()
      }
    })
    doc.body.append(popup)
    select.setAttribute('aria-expanded', 'true')
    popup.querySelector('[aria-selected="true"]')?.focus()
    outside = event => { if (!popup?.contains(event.target) && event.target !== select) close() }
    doc.addEventListener('pointerdown', outside, true)
    observer = new MutationObserver(() => { if (!select.isConnected) close() })
    observer.observe(doc.body, { childList: true, subtree: true })
  }
  select.setAttribute('aria-haspopup', 'listbox')
  select.addEventListener('pointerdown', event => { if (event.button === 0) { event.preventDefault(); popup ? close() : open() } })
  select.addEventListener('keydown', event => {
    if ([' ', 'Enter', 'ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); event.stopPropagation(); open() }
    else if (event.key === 'Escape') close()
  })
  attachPoseThumbnail(select, poses.find(p => p.id === select.value))
}
