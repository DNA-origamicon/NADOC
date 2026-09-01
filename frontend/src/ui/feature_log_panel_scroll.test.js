import { describe, expect, it } from 'vitest'

import {
  initFeatureLogPanel, isFeatureLogAtBottom, scrollFeatureLogToBottom,
} from './feature_log_panel.js'

function scrollBox({ scrollHeight = 1000, clientHeight = 200, scrollTop = 0 } = {}) {
  const el = document.createElement('div')
  Object.defineProperties(el, {
    scrollHeight: { configurable: true, value: scrollHeight },
    clientHeight: { configurable: true, value: clientHeight },
    scrollTop: { configurable: true, writable: true, value: scrollTop },
  })
  return el
}

describe('feature log bottom following', () => {
  it('recognizes the bottom with a small layout tolerance', () => {
    expect(isFeatureLogAtBottom(scrollBox({ scrollTop: 800 }))).toBe(true)
    expect(isFeatureLogAtBottom(scrollBox({ scrollTop: 794 }))).toBe(true)
    expect(isFeatureLogAtBottom(scrollBox({ scrollTop: 780 }))).toBe(false)
  })

  it('scrolls to the newest entry without overshooting short lists', () => {
    const long = scrollBox({ scrollTop: 100 })
    scrollFeatureLogToBottom(long)
    expect(long.scrollTop).toBe(800)

    const short = scrollBox({ scrollHeight: 100, clientHeight: 200, scrollTop: 25 })
    scrollFeatureLogToBottom(short)
    expect(short.scrollTop).toBe(0)
  })

  it('pins the loadout controls and renders compact feature rows', () => {
    const previousResizeObserver = globalThis.ResizeObserver
    const previousRaf = globalThis.requestAnimationFrame
    globalThis.ResizeObserver = class { observe() {} disconnect() {} }
    globalThis.requestAnimationFrame = () => 1
    document.body.innerHTML = `
      <div id="left-panel">
        <div class="tab-content">
          <h2 id="feature-log-panel-heading"><span>Feature Log</span></h2>
          <span id="feature-log-panel-arrow"></span>
          <div id="feature-log-panel-body"></div>
        </div>
      </div>`
    const state = {
      currentDesign: {
        feature_log_cursor: -1,
        feature_log: [{
          feature_type: 'snapshot', op_kind: 'bundle-create', label: 'Bundle',
          params: { length_bp: 20 },
        }],
        loadouts: [{ id: 'main', name: 'Main' }],
        active_loadout_id: 'main',
        cluster_transforms: [], deformations: [], overhangs: [],
      },
      currentAssembly: null, assemblyActive: false,
    }
    const store = {
      getState: () => state,
      subscribeSlice: () => () => {},
    }

    try {
      initFeatureLogPanel(store, { api: {} })
      const bar = document.querySelector('.fl-loadout-bar')
      expect(bar.style.position).toBe('sticky')
      expect(bar.style.top).toBe('0px')

      const row = document.querySelector('#fl-list [data-fl-row="1"]')
      expect(getComputedStyle(row).paddingTop).toBe('1px')
      expect(getComputedStyle(row).gap).toBe('6px')
      const action = row.querySelector('button')
      expect(getComputedStyle(action).height).toBe('15px')
      expect(getComputedStyle(action).paddingTop).toBe('0px')
    } finally {
      document.body.innerHTML = ''
      globalThis.ResizeObserver = previousResizeObserver
      globalThis.requestAnimationFrame = previousRaf
    }
  })
})
