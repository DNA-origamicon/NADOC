/** Keep top-menu dropdowns and nested flyouts inside the viewport. */
export function initMenuFlyouts(root = document, viewport = window) {
  const menuBar = root.getElementById('menu-bar')
  if (!menuBar) return { refresh() {}, destroy() {} }

  function positionDropdown(dropdown) {
    if (!dropdown) return
    dropdown.classList.remove('dropdown--align-right')
    const rect = dropdown.getBoundingClientRect()
    if (rect.right > viewport.innerWidth - 4) dropdown.classList.add('dropdown--align-right')
  }

  function positionSubmenu(submenu) {
    if (!submenu) return
    submenu.classList.remove('submenu--open-left')
    const parent = submenu.parentElement?.getBoundingClientRect()
    const width = submenu.getBoundingClientRect().width || submenu.offsetWidth
    if (parent && parent.right + width > viewport.innerWidth - 4) {
      submenu.classList.add('submenu--open-left')
    }
  }

  function refresh() {
    for (const dropdown of menuBar.querySelectorAll(':scope > .menu-item > .dropdown')) {
      if (dropdown.getClientRects().length) positionDropdown(dropdown)
    }
    for (const submenu of menuBar.querySelectorAll('.submenu')) {
      if (submenu.getClientRects().length) positionSubmenu(submenu)
    }
  }

  const enter = event => {
    const item = event.target.closest?.('.submenu-item')
    if (item && menuBar.contains(item)) positionSubmenu(item.querySelector(':scope > .submenu'))
    const top = event.target.closest?.('.menu-item')
    if (top?.parentElement === menuBar) positionDropdown(top.querySelector(':scope > .dropdown'))
  }
  menuBar.addEventListener('pointerover', enter)
  menuBar.addEventListener('focusin', enter)
  viewport.addEventListener('resize', refresh)
  return {
    refresh,
    destroy() {
      menuBar.removeEventListener('pointerover', enter)
      menuBar.removeEventListener('focusin', enter)
      viewport.removeEventListener('resize', refresh)
    },
  }
}
