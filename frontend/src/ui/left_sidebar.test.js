// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { initLeftSidebar } from './left_sidebar.js'

const TABS = ['feature-log', 'dynamics', 'scene', 'photo', 'plates']

function makeSidebar() {
  document.body.innerHTML = `
    <aside id="left-panel"></aside>
    <nav id="left-tab-strip">
      ${TABS.map(tab => `<button data-tab="${tab}"></button>`).join('')}
    </nav>
    <button id="left-tab-toggle"></button>
    ${TABS.map(tab => `<section id="tab-content-${tab}"></section>`).join('')}
  `
  const state = { simulationTabActive: false, currentDesign: null }
  const deps = {
    store: {
      getState: () => state,
      setState: patch => Object.assign(state, patch),
    },
    animPlayer: { stop: vi.fn(), setDisablePoses: vi.fn() },
    trajectoryKeyframes: { isPreviewing: vi.fn(() => false) },
    seekFeaturesWithDelta: vi.fn(),
    photoMode: { enter: vi.fn(), exit: vi.fn() },
    animPanel: { resumePreview: vi.fn() },
  }
  return { controller: initLeftSidebar(deps), deps, state }
}

describe('initLeftSidebar', () => {
  beforeEach(() => {
    localStorage.clear()
    delete window.__leftSidebar
  })

  it('opens and collapses the active tab with persisted state', () => {
    const { controller } = makeSidebar()
    expect(controller.isCollapsed()).toBe(true)
    document.querySelector('[data-tab="feature-log"]').click()
    expect(controller.isCollapsed()).toBe(false)
    expect(document.getElementById('left-panel').classList.contains('hidden')).toBe(false)
    document.querySelector('[data-tab="feature-log"]').click()
    expect(controller.isCollapsed()).toBe(true)
    expect(JSON.parse(localStorage.getItem('nadoc.leftSidebar.v1'))).toEqual({
      activeTab: 'feature-log', collapsed: true,
    })
  })

  it('owns photo-mode entry and exit across tab changes', () => {
    const { controller, deps } = makeSidebar()
    controller.setActiveTab('photo')
    expect(deps.photoMode.enter).toHaveBeenCalledOnce()
    controller.setActiveTab('scene')
    expect(deps.photoMode.exit).toHaveBeenCalled()
    expect(controller.getActiveTab()).toBe('scene')
  })

  it('does not restore the in-memory-only photo tab after reload', () => {
    localStorage.setItem('nadoc.leftSidebar.v1', JSON.stringify({
      activeTab: 'photo', collapsed: false,
    }))
    const { controller } = makeSidebar()
    expect(controller.getActiveTab()).toBe('feature-log')
    expect(controller.isCollapsed()).toBe(false)
  })

  it('does not stop or re-seek geometry when opening Plates & tubes from Animations', () => {
    const { controller, deps } = makeSidebar()
    controller.setActiveTab('scene')
    deps.animPlayer.stop.mockClear()
    deps.seekFeaturesWithDelta.mockClear()

    controller.setActiveTab('plates')

    expect(deps.animPlayer.stop).not.toHaveBeenCalled()
    expect(deps.seekFeaturesWithDelta).not.toHaveBeenCalled()
    expect(controller.getActiveTab()).toBe('plates')
  })
})
