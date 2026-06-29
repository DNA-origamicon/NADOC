import { describe, it, expect, beforeAll, vi } from 'vitest'
import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

// The cyan(A)/magenta(B) overhang highlight, exercised with an INJECTED fake
// glow factory + fake designRenderer — so the test never imports the real
// glow_layer.js (its canvas IIFE throws under jsdom). Separate file → fresh
// module instance.

const OH1 = { id: 'ovhg_h1_5_5p', label: 'OH1' }
const OH2 = { id: 'ovhg_h2_9_3p', label: 'OH2' }
// 2 beads on OH1, 3 on OH2, 1 unrelated.
const ENTRIES = [
  { nuc: { overhang_id: 'ovhg_h1_5_5p' }, pos: {} },
  { nuc: { overhang_id: 'ovhg_h1_5_5p' }, pos: {} },
  { nuc: { overhang_id: 'ovhg_h2_9_3p' }, pos: {} },
  { nuc: { overhang_id: 'ovhg_h2_9_3p' }, pos: {} },
  { nuc: { overhang_id: 'ovhg_h2_9_3p' }, pos: {} },
  { nuc: { overhang_id: null }, pos: {} },
]

describe('overhang connections — cyan/magenta overhang highlight', () => {
  let store, glows, createGlowLayer
  beforeAll(() => {
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-list': 'div', 'oconn-popover': 'div',
    })
    glows = []
    createGlowLayer = vi.fn((_scene, _color, _scale, _name) => {
      const layer = { setEntries: vi.fn(e => { layer.lastEntries = e }), clear: vi.fn(), lastEntries: null }
      glows.push(layer)
      return layer
    })
    store = createMockStore({
      currentDesign: { overhangs: [OH1, OH2], strands: [], overhang_connections: [], overhang_bindings: [] },
    })
    const designRenderer = { getBackboneEntries: () => ENTRIES }
    initOverhangConnectionsPanel({ store, scene: {}, designRenderer, createGlowLayer })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // expand
  })

  it('creates a cyan A layer and a magenta B layer', () => {
    expect(glows).toHaveLength(2)
    expect(createGlowLayer.mock.calls[0][1]).toBe(0x00e1ff)   // A = cyan
    expect(createGlowLayer.mock.calls[1][1]).toBe(0xff36c6)   // B = magenta
  })

  it('glows over each dropdown overhang while open', () => {
    store.setState({ multiSelectedOverhangIds: ['ovhg_h1_5_5p', 'ovhg_h2_9_3p'] })
    expect(glows[0].lastEntries).toHaveLength(2)   // A = OH1 → 2 beads
    expect(glows[1].lastEntries).toHaveLength(3)   // B = OH2 → 3 beads
  })

  it('clears both glows when the section collapses', () => {
    glows[0].clear.mockClear()
    glows[1].clear.mockClear()
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // collapse
    expect(glows[0].clear).toHaveBeenCalled()
    expect(glows[1].clear).toHaveBeenCalled()
  })
})
