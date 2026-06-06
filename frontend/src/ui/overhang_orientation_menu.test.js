/**
 * Unit tests for the overhang-orientation right-click context menu
 * (ISSUE-1 Phase 2a-orientation — migration onto the shared createContextMenu
 * primitive). Pure consolidation: same items, now rendered via `.context-menu`
 * markup with the Representation flyout riding in as a `{ type:'custom' }` item.
 *
 * Pins: item set + ordering, the single-vs-multi overhang gating (Set Label /
 * Generate only for a single overhang), the danger class on Clear All Overhangs,
 * the Representation flyout passthrough is present, and each item drives the
 * right api call. Uses the REAL representation_overrides helpers so the custom
 * flyout element is exercised, not stubbed.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initOverhangOrientationMenu } from './overhang_orientation_menu.js'
import {
  overhangsToSegments,
  editOverridesForSegments,
  createRepresentationMenuItem,
} from '../scene/representation_overrides.js'

const flush = () => new Promise((r) => setTimeout(r, 0))

function makeDeps(design = {}) {
  const store = createMockStore({ currentDesign: { helices: [{ id: 'h0' }], ...design } })
  const api = {
    patchOverhangRotationsBatch: vi.fn().mockResolvedValue(undefined),
    patchOverhang: vi.fn(),
    generateBinderForOverhang: vi.fn().mockResolvedValue(undefined),
    saveRepresentationOverrides: vi.fn(),
    clearOverhangs: vi.fn(),
  }
  const assemblyRenderer = { invalidateInstance: vi.fn(), rebuild: vi.fn().mockResolvedValue(undefined) }
  const openOverhangsManager = vi.fn()
  const orientPanel = { open: vi.fn() }
  return {
    deps: {
      api, store, assemblyRenderer, openOverhangsManager,
      getOrientPanel: () => orientPanel,
      overhangsToSegments, editOverridesForSegments, createRepresentationMenuItem,
    },
    orientPanel,
  }
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

describe('initOverhangOrientationMenu', () => {
  let deps, orientPanel
  beforeEach(() => {
    ({ deps, orientPanel } = makeDeps())
  })

  it('renders via the shared primitive with the single-overhang item set', () => {
    initOverhangOrientationMenu(deps).show(['o1'], 10, 20)

    expect(document.querySelector('.context-menu')).toBeTruthy()
    expect(menuItems().map((el) => el.textContent.trim())).toEqual([
      'Edit Orientation',
      'Reset Orientation',
      'Set Label…',
      'Generate OH binding strand',
      'Open Overhangs Manager…',
      'Clear All Overhangs',
    ])
    // The Representation flyout rode in as a custom item (not a clickable row).
    expect(document.querySelector('.context-menu').textContent).toContain('Representation')
  })

  it('hides Set Label / Generate for a multi-overhang selection', () => {
    initOverhangOrientationMenu(deps).show(['o1', 'o2'], 0, 0)
    expect(itemByLabel('Set Label…')).toBeFalsy()
    expect(itemByLabel('Generate OH binding strand')).toBeFalsy()
    expect(itemByLabel('Edit Orientation')).toBeTruthy()
    expect(itemByLabel('Clear All Overhangs')).toBeTruthy()
  })

  it('marks Clear All Overhangs with the danger class', () => {
    initOverhangOrientationMenu(deps).show(['o1'], 0, 0)
    expect(itemByLabel('Clear All Overhangs').classList.contains('context-menu__item--danger')).toBe(true)
  })

  it('Edit Orientation opens the orientation panel with the clicked ids', () => {
    initOverhangOrientationMenu(deps).show(['o1', 'o2'], 0, 0)
    itemByLabel('Edit Orientation').click()
    expect(orientPanel.open).toHaveBeenCalledWith(['o1', 'o2'])
  })

  it('Reset Orientation batches identity rotations for every clicked overhang', async () => {
    initOverhangOrientationMenu(deps).show(['o1', 'o2'], 0, 0)
    itemByLabel('Reset Orientation').click()
    await flush()
    expect(deps.api.patchOverhangRotationsBatch).toHaveBeenCalledWith([
      { overhang_id: 'o1', rotation: [0, 0, 0, 1] },
      { overhang_id: 'o2', rotation: [0, 0, 0, 1] },
    ])
  })

  it('Generate OH binding strand calls the api for the single overhang', async () => {
    initOverhangOrientationMenu(deps).show(['o1'], 0, 0)
    itemByLabel('Generate OH binding strand').click()
    await flush()
    expect(deps.api.generateBinderForOverhang).toHaveBeenCalledWith('o1')
  })

  it('Open Overhangs Manager forwards the clicked ids when a design has helices', () => {
    initOverhangOrientationMenu(deps).show(['o1'], 0, 0)
    itemByLabel('Open Overhangs Manager…').click()
    expect(deps.openOverhangsManager).toHaveBeenCalledWith(['o1'])
  })

  it('Open Overhangs Manager is a no-op with no helices', () => {
    const { deps: d } = makeDeps({ helices: [] })
    initOverhangOrientationMenu(d).show(['o1'], 0, 0)
    itemByLabel('Open Overhangs Manager…').click()
    expect(d.openOverhangsManager).not.toHaveBeenCalled()
  })

  it('Clear All Overhangs calls the bulk api', () => {
    initOverhangOrientationMenu(deps).show(['o1'], 0, 0)
    itemByLabel('Clear All Overhangs').click()
    expect(deps.api.clearOverhangs).toHaveBeenCalled()
  })

  it('Set Label… patches the overhang label from the prompt', () => {
    const spy = vi.spyOn(globalThis, 'prompt').mockReturnValue('  tag-7  ')
    deps.store.setState({ currentDesign: { helices: [{ id: 'h0' }], overhangs: [{ id: 'o1', label: 'old' }] } })
    initOverhangOrientationMenu(deps).show(['o1'], 0, 0)
    itemByLabel('Set Label…').click()
    expect(deps.api.patchOverhang).toHaveBeenCalledWith('o1', { label: 'tag-7' })
    spy.mockRestore()
  })

  it('Set Label… cancel (prompt null) does not patch', () => {
    const spy = vi.spyOn(globalThis, 'prompt').mockReturnValue(null)
    initOverhangOrientationMenu(deps).show(['o1'], 0, 0)
    itemByLabel('Set Label…').click()
    expect(deps.api.patchOverhang).not.toHaveBeenCalled()
    spy.mockRestore()
  })

  it('hide() removes the open menu; re-show() does not stack duplicates', () => {
    const menu = initOverhangOrientationMenu(deps)
    menu.show(['o1'], 0, 0)
    menu.show(['o2'], 0, 0)
    expect(document.querySelectorAll('.context-menu').length).toBe(1)
    menu.hide()
    expect(document.querySelector('.context-menu')).toBeFalsy()
  })
})
