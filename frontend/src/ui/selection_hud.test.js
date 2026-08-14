// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'
import { initSelectionHud } from './selection_hud.js'

describe('initSelectionHud', () => {
  it('summarizes canonical and renderer-owned selection kinds', () => {
    document.body.innerHTML = '<div id="selection-count-hud"></div>'
    const state = { selection: { items: [{ kind: 'strand' }, { kind: 'end' }] } }
    const hud = initSelectionHud({
      store: { getState: () => state, subscribe: vi.fn(() => vi.fn()) },
      selectionManager: {
        getMultiOverhangs: () => [{ id: 'o1' }, { id: 'o2' }],
        getCtrlBeads: () => [],
      },
      selectedCrossoverRefs: () => [{ id: 'x1' }],
    })
    hud.update()
    expect(document.getElementById('selection-count-hud').textContent)
      .toBe('1 strand · 2 overhangs · 1 crossover · 1 end selected')
  })

  it('hides itself when selection is empty', () => {
    document.body.innerHTML = '<div id="selection-count-hud"></div>'
    const hud = initSelectionHud({
      store: { getState: () => ({ selection: { items: [] } }), subscribe: () => vi.fn() },
      selectionManager: { getMultiOverhangs: () => [], getCtrlBeads: () => [] },
      selectedCrossoverRefs: () => [],
    })
    hud.update()
    expect(document.getElementById('selection-count-hud').style.display).toBe('none')
  })
})
