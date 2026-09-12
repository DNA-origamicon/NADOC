// @vitest-environment jsdom
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { initLeftSidebar } from './left_sidebar.js'
const TABS = ['feature-log', 'dynamics', 'scene', 'photo', 'plates']
let controller
function makeSidebar({ budget = 1600 } = {}) {
  document.body.innerHTML = `<aside id="left-panel">${TABS.map(tab => `<section id="tab-content-${tab}"><input value="shared"></section>`).join('')}</aside><nav id="left-tab-strip">${TABS.map(tab => `<button data-tab="${tab}"></button>`).join('')}</nav><button id="left-tab-toggle"></button>`
  const state = { simulationControlsOpen: false, simulationTabActive: false }
  const deps = {
    store: { getState: () => state, setState: patch => Object.assign(state, patch) },
    photoMode: { enter: vi.fn(), exit: vi.fn() }, animPlayer: { stop: vi.fn() }, seekFeaturesWithDelta: vi.fn(),
    getAvailableWidth: () => budget,
  }
  controller = initLeftSidebar(deps)
  return { controller, deps, state }
}
beforeEach(() => { localStorage.clear(); delete window.__leftSidebar })
afterEach(() => { controller?.dispose(); document.body.innerHTML = '' })
describe('sidebar stack', () => {
  it('appends duplicate types left to right and closes just the chosen instance', () => {
    const { controller } = makeSidebar()
    controller.setActiveTab('scene'); controller.setActiveTab('scene')
    expect(controller.getOpenPanels()).toEqual(['feature-log', 'scene', 'scene'])
    const copies = [...document.querySelectorAll('[data-panel-type="scene"]')]
    copies[0].querySelector('.sidebar-close').click()
    expect(controller.getOpenPanels()).toEqual(['feature-log', 'scene'])
    expect(copies[1].isConnected).toBe(true)
  })
  it('disallows excess instances and explains the limit', () => {
    const { controller } = makeSidebar({ budget: 560 })
    expect(controller.setActiveTab('photo')).toBe(true)
    expect(controller.setActiveTab('scene')).toBe(false)
    expect(controller.getOpenPanels()).toEqual(['feature-log', 'photo'])
    expect(document.querySelector('[role="status"]').textContent).toContain('No room')
  })
  it('resizes one instance independently, respecting capacity', () => {
    const { controller } = makeSidebar({ budget: 650 })
    controller.setActiveTab('scene')
    const handles = document.querySelectorAll('[role="separator"]')
    for (let i = 0; i < 20; i++) handles[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    expect(controller.getInstances().map(i => i.width)).toEqual([370, 280])
    handles[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
    expect(controller.getInstances().map(i => i.width)).toEqual([370, 260])
  })
  it('never changes lighting, reference visibility or playback through navigation', () => {
    const { controller, deps, state } = makeSidebar()
    for (const id of TABS) controller.setActiveTab(id)
    controller.toggleCollapsed(); controller.toggleCollapsed()
    controller.selectTab('feature-log')
    controller.close(controller.getInstances()[0].id)
    expect(deps.photoMode.enter).not.toHaveBeenCalled()
    expect(deps.photoMode.exit).not.toHaveBeenCalled()
    expect(deps.animPlayer.stop).not.toHaveBeenCalled()
    expect(deps.seekFeaturesWithDelta).not.toHaveBeenCalled()
    expect(state.simulationTabActive).toBe(false)
  })
  it('migrates expanded sections and persists duplicates with widths', () => {
    localStorage.setItem('nadoc.leftSidebar.v2', JSON.stringify({ activeTab: 'photo', openPanels: ['photo', 'scene'], collapsed: false }))
    const { controller } = makeSidebar()
    controller.setActiveTab('photo')
    expect(controller.getOpenPanels()).toEqual(['photo', 'scene', 'photo'])
    expect(JSON.parse(localStorage.getItem('nadoc.leftSidebar.v3')).instances.map(i => i.type)).toEqual(['photo', 'scene', 'photo'])
  })
  it('keeps locked sessions hidden and releases lighting only for teardown', () => {
    const { controller, deps } = makeSidebar()
    document.getElementById('left-panel').classList.add('locked-hidden')
    expect(controller.setActiveTab('photo')).toBe(false)
    controller.collapseForTeardown()
    expect(deps.photoMode.exit).toHaveBeenCalledOnce()
    expect(document.getElementById('left-panel').classList.contains('hidden')).toBe(true)
  })
})
