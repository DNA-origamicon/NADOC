import { afterEach, expect, it, vi } from 'vitest'
import { initSidebarStack } from './sidebar_stack.js'
import { initDetachedSidebars } from './detached_sidebars.js'
import { mountDetachedControlView } from './detached_control_view.js'

const cleanup = []
afterEach(() => { for (const fn of cleanup.splice(0).reverse()) fn(); document.body.replaceChildren(); localStorage.clear() })
function popup() {
  const iframe = document.createElement('iframe'); document.body.append(iframe)
  const win = iframe.contentWindow
  win.focus = vi.fn(); win.close = vi.fn(() => win.dispatchEvent(new win.Event('pagehide'))); win.requestAnimationFrame = vi.fn(() => 1); win.cancelAnimationFrame = vi.fn()
  cleanup.push(() => iframe.remove())
  return win
}
function fixture() {
  document.body.innerHTML = '<button id="menu-view-undock-sidebars"></button><main id="main-area"></main>'
  const main = document.getElementById('main-area')
  const stacks = {}
  for (const side of ['left', 'right']) {
    main.insertAdjacentHTML('beforeend', `<aside id="${side}-panel"><section id="${side}-one"><input value="initial"><button class="action">Apply</button></section><section id="${side}-two">Second</section></aside><nav id="${side}-tab-strip"><button data-tab="one">One</button><button data-tab="two">Two</button></nav>`)
    stacks[side] = initSidebarStack({ side, labels: { one: 'One', two: 'Two' }, panePrefix: `${side}-`, defaultTab: 'one', getAvailableWidth: () => 280 })
    cleanup.push(() => stacks[side].dispose())
  }
  let state = { currentDesign: { id: 'owner' } }
  const listeners = new Set()
  const store = { getState: () => state, subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) } }
  const child = popup(), openWindow = vi.fn(() => child)
  const controller = initDetachedSidebars({ ...stacks, store, openWindow })
  cleanup.push(() => controller.dispose())
  return { ...stacks, controller, child, openWindow, state(patch) { state = patch; for (const fn of listeners) fn() } }
}
it('opens all columns, permits additional tabs beyond the docked budget, and forwards only to its owner', () => {
  const f = fixture(), action = vi.fn()
  document.querySelector('#left-one .action').onclick = action
  f.controller.toggle()
  expect(f.openWindow).toHaveBeenCalledWith('', '_blank', expect.stringContaining('popup'))
  expect(f.child.document.querySelectorAll('.sidebar-column')).toHaveLength(2)
  f.child.document.querySelector('[data-sidebar-source-id=left-one] .action').click()
  expect(action).toHaveBeenCalledOnce()
  f.child.document.querySelector('#left-tab-strip [data-tab="two"]').click()
  expect(f.child.document.querySelectorAll('.sidebar-column')).toHaveLength(3)
  expect(document.body.classList.contains('sidebars-undocked')).toBe(true)
  f.child.document.getElementById('detached-close').click()
  expect(document.body.classList.contains('sidebars-undocked')).toBe(false)
  expect(f.child.close).toHaveBeenCalledOnce()
})
it('blanks on session close, rejects stale controls, and resumes for the next session', () => {
  const f = fixture(), action = vi.fn()
  document.querySelector('#left-one .action').onclick = action
  f.controller.toggle()
  const stale = f.child.document.querySelector('[data-sidebar-source-id=left-one] .action')
  f.state({ currentDesign: null, assemblyActive: false })
  expect(f.child.document.getElementById('detached-workspace').hidden).toBe(true)
  expect(f.child.document.getElementById('detached-closed').textContent).toBe('the session was closed')
  stale.click(); expect(action).not.toHaveBeenCalled()
  f.state({ currentDesign: null, assemblyActive: true })
  expect(f.child.document.getElementById('detached-workspace').hidden).toBe(false)
  f.child.document.querySelector('[data-sidebar-source-id=left-one] .action').click()
  expect(action).toHaveBeenCalledOnce()
})
it('recovers blocked popups without hiding the editor controls', () => {
  const f = fixture(); f.openWindow.mockReturnValue(null)
  const alert = vi.spyOn(window, 'alert').mockImplementation(() => {})
  f.controller.toggle()
  expect(alert).toHaveBeenCalled(); expect(document.body.classList.contains('sidebars-undocked')).toBe(false)
  alert.mockRestore()
})
it('mirrors dynamic controls and forwards native edits and checkbox activation exactly once', async () => {
  const child = popup(), source = document.createElement('section'), host = child.document.createElement('div')
  source.innerHTML = '<input type="checkbox"><input type="text" value="before"><select><option>A</option><option>B</option></select>'
  document.body.append(source); child.document.body.append(host)
  const view = mountDetachedControlView(source, host); cleanup.push(() => view.dispose())
  const clicked = vi.fn(), changed = vi.fn(); source.querySelector('input').onclick = clicked
  source.querySelector('input').onchange = changed
  host.querySelector('input').click()
  expect(source.querySelector('input').checked).toBe(true); expect(clicked).toHaveBeenCalledOnce(); expect(changed).toHaveBeenCalledOnce()
  const text = host.querySelector('input[type=text]'); text.value = 'edited'
  text.dispatchEvent(new child.Event('input', { bubbles: true }))
  expect(source.querySelector('input[type=text]').value).toBe('edited')
  source.insertAdjacentHTML('beforeend', '<button>New action</button>'); await Promise.resolve()
  expect(host.querySelector('button').textContent).toBe('New action')
  source.querySelector('button').disabled = true; await Promise.resolve()
  expect(host.querySelector('button').disabled).toBe(true)
  source.querySelector('button').remove(); await Promise.resolve()
  expect(host.querySelector('button')).toBeNull()
})

it('mirrors dialogs and closes them through the existing controller', async () => {
  const f = fixture(); f.controller.toggle()
  const { createModal } = await import('./primitives/modal.js')
  const modal = createModal({ title: 'Detached action', body: 'Details' })
  modal.open(); await Promise.resolve()
  expect(f.child.document.querySelector('[role=dialog]').textContent).toContain('Detached action')
  f.child.document.querySelector('[aria-label=Close]').click(); await Promise.resolve()
  expect(modal.isOpen()).toBe(false)
  expect(f.child.document.querySelector('[role=dialog]')).toBeNull()
})
it('restores docked controls on native window close', () => {
  const f = fixture(); f.controller.toggle()
  f.child.dispatchEvent(new f.child.Event('pagehide'))
  expect(document.body.classList.contains('sidebars-undocked')).toBe(false)
  expect(f.child.close).not.toHaveBeenCalled()
})
it('gives repeated controls unique IDs with local label targets', () => {
  const child = popup(), source = document.createElement('section')
  source.innerHTML = '<label for="flag">Flag</label><input id="flag" type="checkbox">'
  document.body.append(source)
  const hosts = [child.document.createElement('div'), child.document.createElement('div')]
  for (const host of hosts) { child.document.body.append(host); const view = mountDetachedControlView(source, host); cleanup.push(() => view.dispose()) }
  expect(hosts[0].querySelector('input').id).not.toBe(hosts[1].querySelector('input').id)
  hosts[1].querySelector('label').click()
  expect(source.querySelector('input').checked).toBe(true)
})

it('uses the remote pointer capture and geometry for a slider gesture, restoring the original methods', () => {
  const child = popup(), source = document.createElement('section')
  source.innerHTML = '<div tabindex="0">Drag</div>'; document.body.append(source)
  const host = child.document.createElement('div'); child.document.body.append(host)
  const original = source.firstChild, bounds = original.getBoundingClientRect
  let seen
  original.addEventListener('pointerdown', event => {
    original.setPointerCapture(event.pointerId)
    seen = original.getBoundingClientRect().width
  })
  const view = mountDetachedControlView(source, host); cleanup.push(() => view.dispose())
  const copy = host.querySelector('[tabindex]')
  copy.setPointerCapture = vi.fn(); copy.getBoundingClientRect = () => ({ width: 480 })
  copy.dispatchEvent(new child.Event('pointerdown', { bubbles: true }))
  expect(copy.setPointerCapture).toHaveBeenCalledOnce()
  expect(seen).toBe(480)
  expect(original.getBoundingClientRect).toBe(bounds)
  expect(Object.hasOwn(original, 'setPointerCapture')).toBe(false)
})

it('does not activate a newly disabled owner control or change an already selected radio', () => {
  const child = popup(), source = document.createElement('section'), host = child.document.createElement('div')
  source.innerHTML = '<button>Action</button><input type="radio" checked>'
  document.body.append(source); child.document.body.append(host)
  const action = vi.fn(), change = vi.fn()
  source.querySelector('button').onclick = action; source.querySelector('input').onchange = change
  const view = mountDetachedControlView(source, host); cleanup.push(() => view.dispose())
  source.querySelector('button').disabled = true
  host.querySelector('button').click()
  expect(action).not.toHaveBeenCalled()
  host.querySelector('input').click()
  expect(change).not.toHaveBeenCalled()
})

it('focuses an editor revealed by its controller and forwards the caret position', () => {
  const child = popup(), source = document.createElement('section'), host = child.document.createElement('div')
  source.innerHTML = '<button>Edit</button><input style="display:none" value="ACGT">'
  document.body.append(source); child.document.body.append(host)
  const input = source.querySelector('input')
  source.querySelector('button').onclick = () => { input.style.display = ''; input.focus() }
  const view = mountDetachedControlView(source, host); cleanup.push(() => view.dispose())
  host.querySelector('button').click()
  const copy = host.querySelector('input')
  expect(child.document.activeElement).toBe(copy)
  copy.value = 'ACAGT'; copy.setSelectionRange(3, 3)
  copy.dispatchEvent(new child.Event('input', { bubbles: true }))
  expect(input.value).toBe('ACAGT'); expect(input.selectionStart).toBe(3)
})
