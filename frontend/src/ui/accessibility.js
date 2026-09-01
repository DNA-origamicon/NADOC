import { getShortcuts } from '../input/shortcuts.js'

function focusableItems(container) {
  return [...container.querySelectorAll('button:not(:disabled), [role="menuitem"][tabindex="0"]')]
    .filter(el => !el.closest('.submenu') || el.closest('.submenu').parentElement.classList.contains('a11y-open'))
}

function closeMenus(menuBar, { restoreFocus = false } = {}) {
  const openButton = menuBar.querySelector('.menu-item.a11y-open > button')
  for (const item of menuBar.querySelectorAll('.a11y-open')) item.classList.remove('a11y-open')
  for (const button of menuBar.querySelectorAll('.menu-item > button')) button.setAttribute('aria-expanded', 'false')
  if (restoreFocus) openButton?.focus()
}

function shortcutLabel(shortcut) {
  const key = shortcut.key.length === 1 ? shortcut.key.toUpperCase() : shortcut.key
  return [shortcut.ctrl && 'Ctrl', shortcut.shift && 'Shift', shortcut.alt && 'Alt', key]
    .filter(Boolean).join(' ')
}

const WORKFLOWS = [
  ['Representations', s => /^F[1-8]$/i.test(s.key)],
  ['Automation & sequencing', s => /^[1-6]$/.test(s.key)],
  ['Selection', s => ['e', 'q', 's'].includes(s.key.toLowerCase()) && !s.ctrl],
  ['View & display', s => ['f', 'n', 'v', 'x', 'g', 'c', 'p', 'u', 'k', '/', 'l', '`'].includes(s.key.toLowerCase()) && !s.ctrl],
  ['Tools & interaction', s => /measure|blunt|overhang|ligat|translate|rotate|delete selected/i.test(s.description)],
  ['File & editing', s => !!s.ctrl && !/command palette/i.test(s.description)],
  ['Workspace', s => true],
]

export function shortcutWorkflows(shortcuts) {
  const groups = WORKFLOWS.map(([title]) => ({ title, shortcuts: [] }))
  for (const shortcut of shortcuts) {
    groups[WORKFLOWS.findIndex(([, matches]) => matches(shortcut))].shortcuts.push(shortcut)
  }
  return groups.filter(group => group.shortcuts.length)
}

export function populateShortcutHelp(root = document) {
  const body = root.querySelector('#help-modal .hk-body')
  if (!body) return
  const shortcuts = getShortcuts().filter(s => s.description)
  body.replaceChildren()
  const columns = [document.createElement('div'), document.createElement('div')]
  for (const column of columns) column.className = 'hk-column'
  shortcutWorkflows(shortcuts).forEach((group, groupIndex) => {
    const section = document.createElement('div')
    section.className = 'hk-section'
    const title = document.createElement('div')
    title.className = 'hk-section-title'
    title.textContent = group.title
    section.appendChild(title)
    for (const shortcut of group.shortcuts) {
      const row = document.createElement('div')
      row.className = 'hk-row'
      const description = document.createElement('span')
      description.className = 'hk-desc'
      description.textContent = shortcut.description
      const key = document.createElement('span')
      key.className = 'hk-key'
      key.textContent = shortcutLabel(shortcut)
      row.append(description, key)
      section.appendChild(row)
    }
    columns[groupIndex % 2].appendChild(section)
  })
  body.append(...columns)
}

const NATIVE_INTERACTIVE = 'button, a[href], input, select, textarea, summary, label'

function keyboardEnableClickable(el) {
  if (!(el instanceof HTMLElement) || el.matches(NATIVE_INTERACTIVE) || el.id === 'canvas') return
  if (!/cursor\s*:\s*pointer/i.test(el.getAttribute('style') ?? '')) return
  if (!el.hasAttribute('role')) el.setAttribute('role', 'button')
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0')
  if (el.dataset.a11yClickKey === '1') return
  el.dataset.a11yClickKey = '1'
  el.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return
    e.preventDefault()
    el.click()
  })
}

function enableClickableTree(node) {
  if (!(node instanceof Element)) return
  keyboardEnableClickable(node)
  for (const el of node.querySelectorAll('[style*="cursor"]')) keyboardEnableClickable(el)
}

/** Add keyboard semantics to the legacy top menu and collapsible panel headings. */
export function initAccessibility(root = document) {
  const menuBar = root.getElementById('menu-bar')
  if (menuBar) {
    menuBar.setAttribute('role', 'menubar')
    const topItems = [...menuBar.querySelectorAll(':scope > .menu-item')]
    for (const item of topItems) {
      const button = item.querySelector(':scope > button')
      const dropdown = item.querySelector(':scope > .dropdown')
      if (!button || !dropdown) continue
      button.setAttribute('aria-haspopup', 'menu')
      button.setAttribute('aria-expanded', 'false')
      dropdown.setAttribute('role', 'menu')
      button.addEventListener('click', e => {
        e.stopPropagation()
        const opening = !item.classList.contains('a11y-open')
        closeMenus(menuBar)
        item.classList.toggle('a11y-open', opening)
        button.setAttribute('aria-expanded', String(opening))
      })
      button.addEventListener('keydown', e => {
        const index = topItems.indexOf(item)
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          e.preventDefault()
          const delta = e.key === 'ArrowRight' ? 1 : -1
          topItems[(index + delta + topItems.length) % topItems.length].querySelector(':scope > button')?.focus()
        } else if (e.key === 'ArrowDown') {
          e.preventDefault()
          item.classList.add('a11y-open')
          button.setAttribute('aria-expanded', 'true')
          focusableItems(dropdown)[0]?.focus()
        }
      })
    }

    for (const submenuItem of menuBar.querySelectorAll('.submenu-item')) {
      submenuItem.setAttribute('role', 'menuitem')
      submenuItem.setAttribute('tabindex', '0')
      submenuItem.setAttribute('aria-haspopup', 'menu')
      submenuItem.addEventListener('keydown', e => {
        if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'ArrowRight') return
        e.preventDefault()
        submenuItem.classList.add('a11y-open')
        submenuItem.querySelector('.submenu button:not(:disabled)')?.focus()
      })
    }

    menuBar.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeMenus(menuBar, { restoreFocus: true })
      }
    })
    root.addEventListener('click', e => { if (!menuBar.contains(e.target)) closeMenus(menuBar) })
  }

  const canvas = root.getElementById('canvas')
  if (canvas) {
    canvas.setAttribute('tabindex', '0')
    canvas.setAttribute('role', 'application')
    canvas.setAttribute('aria-label', 'NADOC interactive 3D molecular design workspace')
  }

  enableClickableTree(root.documentElement)
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes') keyboardEnableClickable(record.target)
      for (const node of record.addedNodes) enableClickableTree(node)
    }
  })
  observer.observe(root.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style'] })

  root.getElementById('menu-help-hotkeys')?.addEventListener('click', () => populateShortcutHelp(root))
  return { closeMenus: () => closeMenus(menuBar), destroy: () => observer.disconnect() }
}
