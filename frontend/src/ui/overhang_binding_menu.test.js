/**
 * Unit tests for the overhang-binding right-click context menu
 * (ISSUE-1 Phase 2a — migration onto the shared createContextMenu primitive).
 *
 * Pins the migration: the menu still renders header + Bind/Unbind + Delete via
 * the shared primitive (`.context-menu` markup), the Delete item carries the
 * danger class, the Bind/Unbind label tracks `binding.bound`, and clicking each
 * item drives the right api call (Delete gated on showConfirm).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initOverhangBindingMenu } from './overhang_binding_menu.js'

const flush = () => new Promise((r) => setTimeout(r, 0))

function makeDeps(bindings) {
  const store = createMockStore({ currentDesign: { overhang_bindings: bindings } })
  const api = {
    patchOverhangBinding: vi.fn().mockResolvedValue(undefined),
    deleteOverhangBinding: vi.fn().mockResolvedValue(undefined),
  }
  const showToast = vi.fn()
  const showConfirm = vi.fn().mockResolvedValue(true)
  return { store, api, showToast, showConfirm }
}

function menuItems() {
  return Array.from(document.querySelectorAll('.context-menu__item'))
}
function itemByLabel(label) {
  return menuItems().find((el) => el.textContent.trim() === label)
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('initOverhangBindingMenu', () => {
  let deps
  beforeEach(() => {
    deps = makeDeps([
      { id: 'b1', name: 'oh-A↔oh-B', bound: false },
      { id: 'b2', name: 'oh-C↔oh-D', bound: true },
    ])
  })

  it('renders header + Bind + Delete via the shared primitive for an unbound binding', () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('b1', 10, 20)

    // Rendered through createContextMenu → `.context-menu` markup.
    expect(document.querySelector('.context-menu')).toBeTruthy()
    expect(document.querySelector('.context-menu__header').textContent).toBe('oh-A↔oh-B')
    expect(menuItems().map((el) => el.textContent.trim())).toEqual(['Bind', 'Delete binding'])
  })

  it('labels the toggle "Unbind" when the binding is already bound', () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('b2', 0, 0)
    expect(itemByLabel('Unbind')).toBeTruthy()
    expect(itemByLabel('Bind')).toBeFalsy()
  })

  it('marks the Delete item with the danger class', () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('b1', 0, 0)
    expect(itemByLabel('Delete binding').classList.contains('context-menu__item--danger')).toBe(true)
  })

  it('renders nothing for an unknown binding id', () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('nope', 0, 0)
    expect(document.querySelector('.context-menu')).toBeFalsy()
  })

  it('Bind toggles bound via api.patchOverhangBinding', async () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('b1', 0, 0)
    itemByLabel('Bind').click()
    await flush()
    expect(deps.api.patchOverhangBinding).toHaveBeenCalledWith('b1', { bound: true })
  })

  it('Delete calls deleteOverhangBinding only after the user confirms', async () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('b1', 0, 0)
    itemByLabel('Delete binding').click()
    await flush()
    expect(deps.showConfirm).toHaveBeenCalled()
    expect(deps.api.deleteOverhangBinding).toHaveBeenCalledWith('b1')
  })

  it('Delete does NOT call the api when the user cancels the confirm', async () => {
    deps.showConfirm.mockResolvedValue(false)
    const menu = initOverhangBindingMenu(deps)
    menu.show('b1', 0, 0)
    itemByLabel('Delete binding').click()
    await flush()
    expect(deps.api.deleteOverhangBinding).not.toHaveBeenCalled()
  })

  it('hide() removes the open menu; re-show() does not stack duplicates', () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('b1', 0, 0)
    menu.show('b2', 0, 0)
    expect(document.querySelectorAll('.context-menu').length).toBe(1)
    menu.hide()
    expect(document.querySelector('.context-menu')).toBeFalsy()
  })

  it('clicking an item auto-dismisses the menu (primitive behaviour)', async () => {
    const menu = initOverhangBindingMenu(deps)
    menu.show('b1', 0, 0)
    itemByLabel('Bind').click()
    await flush()
    expect(document.querySelector('.context-menu')).toBeFalsy()
  })
})
