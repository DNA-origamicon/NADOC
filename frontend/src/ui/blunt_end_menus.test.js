/**
 * Tests for the blunt-end (domain-end) interaction menus (blunt_end_menus.js).
 *
 * Factory wiring: the sidebar action panel (showPanel/hidePanel) + the
 * right-click context menu (showCtx/hideCtx) + the six action buttons
 * (Extrude continuation / Bend / Twist, one set per surface). The two action
 * surfaces share identical action logic over a captured domain-end info object,
 * so the panel and ctx paths are tested in parallel.
 *
 * startToolAtBp + showToast are module imports → mocked so the Bend/Twist guard
 * branches are observable.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

vi.mock('../scene/deformation_editor.js', () => ({ startToolAtBp: vi.fn() }))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))

import { startToolAtBp } from '../scene/deformation_editor.js'
import { showToast } from './toast.js'
import { initBluntEndMenus } from './blunt_end_menus.js'

const DOM = {
  'blunt-panel-actions': 'div',
  'blunt-panel-empty': 'div',
  'blunt-panel-info': 'div',
  'blunt-end-ctx-menu': 'div',
  'mode-indicator': 'div',
  'blunt-extrude-btn': 'button',
  'blunt-bend-btn': 'button',
  'blunt-twist-btn': 'button',
  'blunt-extrude-btn-ctx': 'button',
  'blunt-bend-btn-ctx': 'button',
  'blunt-twist-btn-ctx': 'button',
}

const flush = () => new Promise(r => setTimeout(r, 0))

function makeDeps(initialState = {}) {
  const store = createMockStore(initialState)
  const api = { getDeformedFrame: vi.fn() }
  const slicePlane = { showDeformed: vi.fn(), showAtEnd: vi.fn() }
  const expandedSpacing = { forceOff: vi.fn() }
  const deformView = { isActive: vi.fn(() => true) }
  const clusterDeformGuard = vi.fn(() => true)
  return { store, api, slicePlane, expandedSpacing, deformView, clusterDeformGuard }
}

const click = (id) => document.getElementById(id).click()

beforeEach(() => {
  mountIds(DOM)
  vi.clearAllMocks()
})

afterEach(clearDom)

describe('blunt-end sidebar panel', () => {
  it('showPanel reveals the action panel, hides the empty placeholder, labels the end', () => {
    const menus = initBluntEndMenus(makeDeps())
    menus.showPanel({ helixId: 3, bp: 7 })
    expect(document.getElementById('blunt-panel-actions').style.display).toBe('block')
    expect(document.getElementById('blunt-panel-empty').style.display).toBe('none')
    expect(document.getElementById('blunt-panel-info').textContent).toBe('helix 3  bp 7')
  })

  it('hidePanel hides the panel and restores the empty placeholder', () => {
    const menus = initBluntEndMenus(makeDeps())
    menus.showPanel({ helixId: 3, bp: 7 })
    menus.hidePanel()
    expect(document.getElementById('blunt-panel-actions').style.display).toBe('none')
    expect(document.getElementById('blunt-panel-empty').style.display).toBe('')
  })
})

describe('blunt-end Extrude (continuation)', () => {
  it('with no deformations: sets plane, forces spacing off, opens slice plane at the axis end', async () => {
    const deps = makeDeps()
    const menus = initBluntEndMenus(deps)
    menus.showPanel({ plane: 'XY', helixId: 2, hasDeformations: false, bp: 5, openSide: 1 })
    click('blunt-extrude-btn')
    await flush()
    expect(deps.store.getState().currentPlane).toBe('XY')
    expect(deps.expandedSpacing.forceOff).toHaveBeenCalled()
    // continuationBp = bp + max(0, openSide) = 5 + 1 = 6
    expect(deps.slicePlane.showAtEnd).toHaveBeenCalledWith(2, 6, true, { defaultDirSign: 1 })
    expect(deps.slicePlane.showDeformed).not.toHaveBeenCalled()
    expect(document.getElementById('mode-indicator').textContent).toContain('CONTINUATION')
    // panel hidden by the action
    expect(document.getElementById('blunt-panel-actions').style.display).toBe('none')
  })

  it('near end (openSide -1) anchors continuationBp at bp (max(0,-1)=0)', async () => {
    const deps = makeDeps()
    const menus = initBluntEndMenus(deps)
    menus.showPanel({ plane: 'XY', helixId: 0, hasDeformations: false, bp: 9, openSide: -1 })
    click('blunt-extrude-btn')
    await flush()
    expect(deps.slicePlane.showAtEnd).toHaveBeenCalledWith(0, 9, true, { defaultDirSign: -1 })
  })

  it('with deformations + deformVisuActive + a frame: shows the deformed continuation', async () => {
    const deps = makeDeps({ deformVisuActive: true })
    deps.api.getDeformedFrame.mockResolvedValue({ some: 'frame' })
    const menus = initBluntEndMenus(deps)
    menus.showPanel({ plane: 'XZ', helixId: 4, hasDeformations: true, bp: 2, openSide: 1 })
    click('blunt-extrude-btn')
    await flush()
    expect(deps.api.getDeformedFrame).toHaveBeenCalledWith(3, 4)
    expect(deps.slicePlane.showDeformed).toHaveBeenCalledWith(
      { some: 'frame' },
      { plane: 'XZ', continuation: true, refHelixId: 4, defaultDirSign: 1 },
    )
    expect(deps.slicePlane.showAtEnd).not.toHaveBeenCalled()
    expect(document.getElementById('mode-indicator').textContent).toContain('DEFORMED CONTINUATION')
  })

  it('no panel info (never shown): click is a no-op', async () => {
    const deps = makeDeps()
    initBluntEndMenus(deps)
    click('blunt-extrude-btn')
    await flush()
    expect(deps.slicePlane.showAtEnd).not.toHaveBeenCalled()
    expect(deps.store.getState().currentPlane).toBeUndefined()
  })
})

describe('blunt-end Bend / Twist', () => {
  it('Bend with deform view active + guard ok: starts the bend tool at the end', () => {
    const deps = makeDeps()
    const menus = initBluntEndMenus(deps)
    menus.showPanel({ helixId: 1, bp: 6, openSide: 1 })
    click('blunt-bend-btn')
    expect(startToolAtBp).toHaveBeenCalledWith('bend', 1, 6, 1)
    expect(showToast).not.toHaveBeenCalled()
  })

  it('Twist starts the twist tool', () => {
    const deps = makeDeps()
    const menus = initBluntEndMenus(deps)
    menus.showPanel({ helixId: 1, bp: 6, openSide: -1 })
    click('blunt-twist-btn')
    expect(startToolAtBp).toHaveBeenCalledWith('twist', 1, 6, -1)
  })

  it('Bend blocked when not in deformed view but design already has deformations: toasts, no tool', () => {
    const deps = makeDeps({ currentDesign: { deformations: [{}] } })
    deps.deformView.isActive.mockReturnValue(false)
    const menus = initBluntEndMenus(deps)
    menus.showPanel({ helixId: 1, bp: 6, openSide: 1 })
    click('blunt-bend-btn')
    expect(showToast).toHaveBeenCalled()
    expect(startToolAtBp).not.toHaveBeenCalled()
  })

  it('Bend blocked when the cluster-deform guard fails: no tool', () => {
    const deps = makeDeps()
    deps.clusterDeformGuard.mockReturnValue(false)
    const menus = initBluntEndMenus(deps)
    menus.showPanel({ helixId: 1, bp: 6, openSide: 1 })
    click('blunt-bend-btn')
    expect(startToolAtBp).not.toHaveBeenCalled()
  })
})

describe('blunt-end right-click context menu', () => {
  it('showCtx positions and reveals the ctx menu', () => {
    const menus = initBluntEndMenus(makeDeps())
    menus.showCtx(120, 80, { helixId: 0, bp: 1, openSide: 1, plane: 'XY' })
    const ctx = document.getElementById('blunt-end-ctx-menu')
    expect(ctx.style.display).toBe('block')
    expect(ctx.style.left).toBe('120px')
    expect(ctx.style.top).toBe('80px')
  })

  it('hideCtx hides the ctx menu', () => {
    const menus = initBluntEndMenus(makeDeps())
    menus.showCtx(120, 80, { helixId: 0, bp: 1, openSide: 1, plane: 'XY' })
    menus.hideCtx()
    expect(document.getElementById('blunt-end-ctx-menu').style.display).toBe('none')
  })

  it('an outside pointerdown dismisses an open ctx menu', () => {
    const menus = initBluntEndMenus(makeDeps())
    menus.showCtx(10, 10, { helixId: 0, bp: 1, openSide: 1, plane: 'XY' })
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(document.getElementById('blunt-end-ctx-menu').style.display).toBe('none')
  })

  it('ctx Extrude runs the same continuation over the ctx info', async () => {
    const deps = makeDeps()
    const menus = initBluntEndMenus(deps)
    menus.showCtx(0, 0, { plane: 'XY', helixId: 7, hasDeformations: false, bp: 3, openSide: 1 })
    click('blunt-extrude-btn-ctx')
    await flush()
    expect(deps.slicePlane.showAtEnd).toHaveBeenCalledWith(7, 4, true, { defaultDirSign: 1 })
    // ctx hidden by the action
    expect(document.getElementById('blunt-end-ctx-menu').style.display).toBe('none')
  })

  it('ctx Bend starts the bend tool over the ctx info', () => {
    const deps = makeDeps()
    const menus = initBluntEndMenus(deps)
    menus.showCtx(0, 0, { helixId: 9, bp: 2, openSide: -1, plane: 'XY' })
    click('blunt-bend-btn-ctx')
    expect(startToolAtBp).toHaveBeenCalledWith('bend', 9, 2, -1)
  })
})
