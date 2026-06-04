/**
 * Empty-space (right-click) context menu extracted from main.js. Owns the show/
 * hide + outside-click / Esc dismissal lifecycle; the menu's action stays in
 * main.js, wired via the `onExtrude` callback. Unit-tested in
 * empty_space_menu.test.js.
 *
 * @param {object} deps
 * @param {HTMLElement} deps.menuEl      the context-menu element (positioned + shown)
 * @param {HTMLElement} deps.extrudeBtn  the "Extrude" button inside it
 * @param {() => void} deps.onExtrude    invoked when Extrude is clicked
 * @returns {{ show:(x:number,y:number)=>void, hide:()=>void }}
 */
export function initEmptySpaceMenu({ menuEl, extrudeBtn, onExtrude }) {
  function hide() { if (menuEl) menuEl.style.display = 'none' }

  function show(x, y) {
    if (!menuEl) return
    menuEl.style.left    = `${x}px`
    menuEl.style.top     = `${y}px`
    menuEl.style.display = 'block'
    const onOutside = (ev) => { if (!menuEl.contains(ev.target)) teardown() }
    const onKey = (ev) => { if (ev.key === 'Escape') teardown() }
    function teardown() {
      hide()
      document.removeEventListener('pointerdown', onOutside, true)
      document.removeEventListener('keydown', onKey, true)
    }
    document.addEventListener('pointerdown', onOutside, true)
    document.addEventListener('keydown', onKey, true)
  }

  extrudeBtn?.addEventListener('click', () => { hide(); onExtrude?.() })

  return { show, hide }
}
