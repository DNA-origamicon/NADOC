import { describe, it, expect, beforeAll } from 'vitest'
import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

// The panel module is a singleton (module-level state + `_inited` guard,
// mirroring the manager popups). So a single comprehensive test drives the
// whole flow against one mount, rather than re-initialising per `it`.

const OH_5P = { id: 'ovhg_h1_5_5p', label: 'OH-A' }
const OH_3P = { id: 'ovhg_h2_9_3p', label: 'OH-B' }

describe('initOverhangConnectionsPanel', () => {
  let els, store

  beforeAll(() => {
    els = mountIds({
      'oconn-heading': 'h2',
      'oconn-arrow': 'span',
      'oconn-body': 'div',
      'oconn-select-a': 'select',
      'oconn-select-b': 'select',
      'oconn-button-box': 'button',
      'oconn-length-row': 'div',
      'oconn-length': 'input',
      'oconn-generate': 'button',
      'oconn-list': 'div',
      'oconn-popover': 'div',
    })
    store = createMockStore({
      currentDesign: { overhangs: [OH_5P, OH_3P], strands: [] },
    })
    initOverhangConnectionsPanel({ store })
  })

  it('populates both dropdowns from the design overhangs (blank + one per overhang)', () => {
    expect(els['oconn-select-a'].options).toHaveLength(3)  // blank + 2
    expect(els['oconn-select-b'].options).toHaveLength(3)
    const valuesA = [...els['oconn-select-a'].options].map(o => o.value)
    expect(valuesA).toContain('ovhg_h1_5_5p')
    expect(valuesA).toContain('ovhg_h2_9_3p')
  })

  it('renders the icon and reflects forbidden polarity pairing live', () => {
    const box = els['oconn-button-box']
    // Default type 'end-to-root' (forbidden iff polarities differ). Select 5p + 3p.
    els['oconn-select-a'].value = 'ovhg_h1_5_5p'
    els['oconn-select-a'].dispatchEvent(new Event('change'))
    els['oconn-select-b'].value = 'ovhg_h2_9_3p'
    els['oconn-select-b'].dispatchEvent(new Event('change'))

    expect(box.innerHTML).toContain('<svg')
    expect(box.innerHTML).toContain('#f5c518')   // ⚠ overlay — 5'/3' is invalid end-to-root
    expect(box.title).toMatch(/parallel duplex/) // forbidden reason surfaced as title
  })

  it('clearing the warning when a valid connection type is picked', () => {
    const box = els['oconn-button-box']
    // root-to-root is forbidden iff polarities MATCH; current pair is 5p/3p → valid.
    const opt = els['oconn-popover'].querySelector('[data-variant="root-to-root"]')
    opt.dispatchEvent(new Event('click', { bubbles: true }))
    expect(box.innerHTML).not.toContain('#f5c518')
    expect(box.title).toBe('Root-to-Root')   // variant label, no forbidden reason
  })

  it('starts collapsed and toggles on heading click', () => {
    // Default collapsed → body hidden, arrow marked collapsed.
    expect(els['oconn-body'].style.display).toBe('none')
    expect(els['oconn-arrow'].classList.contains('is-collapsed')).toBe(true)
    els['oconn-heading'].dispatchEvent(new Event('click'))
    expect(els['oconn-body'].style.display).not.toBe('none')
    expect(els['oconn-arrow'].classList.contains('is-collapsed')).toBe(false)
    els['oconn-heading'].dispatchEvent(new Event('click'))
    expect(els['oconn-body'].style.display).toBe('none')
  })

  it('linker variant shows the length field + an enabled Generate Linker button', () => {
    // Pick a valid linker variant for the 5p/3p pair (ss is valid when ends differ).
    els['oconn-popover'].querySelector('[data-variant="end-to-end-ssdna-linker"]')
      .dispatchEvent(new Event('click', { bubbles: true }))
    els['oconn-select-a'].value = 'ovhg_h1_5_5p'
    els['oconn-select-a'].dispatchEvent(new Event('change'))
    els['oconn-select-b'].value = 'ovhg_h2_9_3p'
    els['oconn-select-b'].dispatchEvent(new Event('change'))

    expect(els['oconn-length-row'].style.display).not.toBe('none')
    // No existing connection for this pair → "Connect".
    expect(els['oconn-generate'].textContent).toBe('Connect')
    expect(els['oconn-generate'].disabled).toBe(false)
  })

  it('direct variant hides length; button is "Connect" (forbidden 5\'/3\' → disabled)', () => {
    els['oconn-popover'].querySelector('[data-variant="end-to-root"]')
      .dispatchEvent(new Event('click', { bubbles: true }))
    expect(els['oconn-length-row'].style.display).toBe('none')
    expect(els['oconn-generate'].textContent).toBe('Connect')
    // end-to-root with the 5'/3' pair is a forbidden polarity → disabled.
    expect(els['oconn-generate'].disabled).toBe(true)
  })

  it('renders the linker list and selects a row on click', () => {
    store.setState({
      currentDesign: {
        overhangs: [OH_5P, OH_3P], strands: [],
        overhang_connections: [{
          id: 'conn1', name: 'L1',
          overhang_a_id: 'ovhg_h1_5_5p', overhang_a_attach: 'free_end',
          overhang_b_id: 'ovhg_h2_9_3p', overhang_b_attach: 'root',
          linker_type: 'ss', length_value: 12, length_unit: 'bp',
        }],
        overhang_bindings: [],
      },
    })
    const rows = els['oconn-list'].querySelectorAll('.oconn-row')
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain('L1')
    expect(rows[0].textContent).toContain('ssDNA')

    rows[0].dispatchEvent(new Event('click', { bubbles: true }))
    expect(els['oconn-list'].querySelector('.oconn-row.is-selected')).not.toBeNull()
    expect(els['oconn-select-a'].value).toBe('ovhg_h1_5_5p')
    expect(els['oconn-select-b'].value).toBe('ovhg_h2_9_3p')
  })

  it('drops a stale selection when the design changes', () => {
    // New design no longer contains overhang A.
    store.setState({ currentDesign: { overhangs: [OH_3P], strands: [] } })
    expect(els['oconn-select-a'].value).toBe('')   // selection A dropped
    expect([...els['oconn-select-a'].options].map(o => o.value)).not.toContain('ovhg_h1_5_5p')
  })
})
