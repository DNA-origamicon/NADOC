/**
 * Add find-in-sequences behavior to a strand spreadsheet.
 *
 * Sequence-bearing cells opt in with `data-search-sequence`. A visible
 * `.sheet-search-text` descendant is optional; when present, the active
 * occurrence is marked precisely. Editable sequence inputs still receive the
 * active-cell highlight even though their text cannot be wrapped in markup.
 */
export function initSequenceSearch({ toolbar, before = null, tbody, scrollContainer }) {
  if (!toolbar || !tbody) return { refresh() {} }

  const wrap = document.createElement('div')
  wrap.className = 'sheet-search-wrap'

  const input = document.createElement('input')
  input.id = 'spreadsheet-sequence-search'
  input.className = 'sheet-search-input'
  input.type = 'search'
  input.placeholder = 'Search sequences…'
  input.setAttribute('aria-label', 'Search spreadsheet sequences')
  input.autocomplete = 'off'
  input.spellcheck = false

  const status = document.createElement('span')
  status.className = 'sheet-search-status'
  status.setAttribute('aria-live', 'polite')

  wrap.append(input, status)
  toolbar.insertBefore(wrap, before)

  let matches = []
  let activeIndex = -1

  function _clearVisuals() {
    for (const cell of tbody.querySelectorAll('.sheet-search-result, .sheet-search-match')) {
      cell.classList.remove('sheet-search-result', 'sheet-search-match')
    }

    const parents = new Set()
    for (const mark of tbody.querySelectorAll('mark.sheet-search-highlight')) {
      const parent = mark.parentNode
      parents.add(parent)
      mark.replaceWith(document.createTextNode(mark.textContent ?? ''))
    }
    for (const parent of parents) parent?.normalize?.()
  }

  function _markOccurrence(match) {
    const root = match.cell.querySelector('.sheet-search-text')
    // Inputs expose their value through data-search-sequence but have no text
    // nodes to wrap. The active-cell highlight remains the visual indication.
    if (!root || root.textContent !== match.sequence) return

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    const textNodes = []
    let offset = 0
    let node
    while ((node = walker.nextNode())) {
      const nextOffset = offset + node.data.length
      if (nextOffset > match.start && offset < match.end) {
        textNodes.push({ node, offset })
      }
      offset = nextOffset
    }

    for (const item of textNodes) {
      const localStart = Math.max(0, match.start - item.offset)
      const localEnd = Math.min(item.node.data.length, match.end - item.offset)
      if (localEnd <= localStart) continue

      let matchedText = item.node
      if (localEnd < matchedText.data.length) matchedText.splitText(localEnd)
      if (localStart > 0) matchedText = matchedText.splitText(localStart)

      const mark = document.createElement('mark')
      mark.className = 'sheet-search-highlight'
      mark.dataset.searchStart = String(match.start)
      matchedText.replaceWith(mark)
      mark.appendChild(matchedText)
    }
  }

  function _scrollWithinSpreadsheet(cell) {
    if (!scrollContainer) return
    const bodyRect = scrollContainer.getBoundingClientRect()

    const cellRect = cell.getBoundingClientRect()
    const top = Math.max(0, scrollContainer.scrollTop
      + cellRect.top - bodyRect.top
      - (scrollContainer.clientHeight - cellRect.height) / 2)

    let left = scrollContainer.scrollLeft
    if (cellRect.left < bodyRect.left) left += cellRect.left - bodyRect.left
    else if (cellRect.right > bodyRect.right) left += cellRect.right - bodyRect.right
    left = Math.max(0, left)

    // scrollIntoView() is deliberately avoided: browsers may also scroll the
    // document, exposing content that sits below the fixed app shell.
    if (typeof scrollContainer.scrollTo === 'function') {
      scrollContainer.scrollTo({ top, left, behavior: 'smooth' })
    } else {
      scrollContainer.scrollTop = top
      scrollContainer.scrollLeft = left
    }
  }

  function _activate({ scroll = false } = {}) {
    for (const cell of tbody.querySelectorAll('.sheet-search-match')) {
      cell.classList.remove('sheet-search-match')
    }
    for (const mark of tbody.querySelectorAll('mark.sheet-search-highlight')) {
      const parent = mark.parentNode
      mark.replaceWith(document.createTextNode(mark.textContent ?? ''))
      parent?.normalize?.()
    }

    if (!matches.length || activeIndex < 0) {
      status.textContent = input.value.trim() ? 'No matches' : ''
      if (input.value.trim()) input.setAttribute('aria-invalid', 'true')
      else input.removeAttribute('aria-invalid')
      return
    }

    activeIndex = ((activeIndex % matches.length) + matches.length) % matches.length
    const match = matches[activeIndex]
    match.cell.classList.add('sheet-search-match')
    _markOccurrence(match)
    status.textContent = `${activeIndex + 1}/${matches.length}`
    input.removeAttribute('aria-invalid')
    if (scroll) _scrollWithinSpreadsheet(match.cell)
  }

  function refresh({ reset = false, scroll = false } = {}) {
    const previousIndex = activeIndex
    _clearVisuals()
    matches = []

    const query = input.value.trim().toLocaleUpperCase()
    if (query) {
      for (const cell of tbody.querySelectorAll('[data-search-sequence]')) {
        const sequence = cell.dataset.searchSequence ?? ''
        const searchable = sequence.toLocaleUpperCase()
        let start = searchable.indexOf(query)
        while (start !== -1) {
          matches.push({ cell, sequence, start, end: start + query.length })
          // Advance one character so overlapping sequence motifs remain findable.
          start = searchable.indexOf(query, start + 1)
        }
      }
    }

    for (const match of matches) match.cell.classList.add('sheet-search-result')
    activeIndex = matches.length ? (reset ? 0 : Math.min(Math.max(previousIndex, 0), matches.length - 1)) : -1
    _activate({ scroll })
  }

  input.addEventListener('input', () => refresh({ reset: true, scroll: true }))
  input.addEventListener('keydown', event => {
    // Keep typed bases and Enter/Escape navigation out of app-wide shortcuts.
    event.stopPropagation()
    if (event.key === 'Enter') {
      event.preventDefault()
      if (!matches.length) return
      activeIndex += event.shiftKey ? -1 : 1
      _activate({ scroll: true })
    } else if (event.key === 'Escape' && input.value) {
      event.preventDefault()
      input.value = ''
      refresh({ reset: true })
    }
  })

  return { refresh, input }
}
