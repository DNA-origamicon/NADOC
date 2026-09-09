import { beforeAll, describe, expect, it } from 'vitest'
import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

describe('Overhang Connections nanoparticle mode', () => {
  let store
  beforeAll(() => {
    const els = mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-list': 'div', 'oconn-popover': 'div',
      'oconn-seq-row-a': 'div', 'oconn-seq-input-a': 'input', 'oconn-seq-gen-a': 'button',
      'oconn-seq-row-b': 'div', 'oconn-seq-input-b': 'input', 'oconn-seq-gen-b': 'button',
    })
    const normal = document.createElement('div')
    els['oconn-body'].appendChild(normal)
    for (const id of ['oconn-select-a', 'oconn-seq-row-a', 'oconn-seq-input-a', 'oconn-seq-gen-a', 'oconn-button-box', 'oconn-select-b', 'oconn-seq-row-b', 'oconn-seq-input-b', 'oconn-seq-gen-b', 'oconn-length-row', 'oconn-length', 'oconn-generate']) normal.appendChild(els[id])
    els['oconn-body'].appendChild(els['oconn-list'])
    store = createMockStore({
      currentGeometry: [],
      currentDesign: {
        nanoparticles: [{ id: 'np1', diameter_nm: 10 }],
        overhangs: [{ id: 'oh1_3p', label: 'Target 1', strand_id: 'origami', sequence: 'ACGT' }],
        strands: [{ id: 'origami' }, { id: 's1', name: 'NP-1:S1', sequence: 'TGCA' }, { id: 's2', name: 'NP-1:S2', sequence: 'AAAA' }],
        nanoparticle_conjugations: [{ nanoparticle_id: 'np1', attach_end: '5p', surface_strands: [
          { strand_id: 's1', helix_id: '__np__1', bound_overhang_id: 'oh1_3p' },
          { strand_id: 's2', helix_id: '__np__2', bound_overhang_id: null },
        ] }],
        nanoparticle_connection_versions: [
          { id: 'v1', name: 'V1', nanoparticle_id: 'np1', strand_id: 's1', overhang_id: 'oh1_3p', applied: true, relaxed: true, residual_nm: 1.25 },
          { id: 'v2', name: 'V2', nanoparticle_id: 'np1', strand_id: 's1', overhang_id: 'oh1_3p', applied: false, relaxed: false },
        ],
        overhang_connections: [], overhang_bindings: [], connection_versions: [],
      },
    })
    initOverhangConnectionsPanel({ store })
    const mode = document.getElementById('oconn-endpoint-mode')
    mode.value = 'nanoparticle'; mode.dispatchEvent(new Event('change'))
  })

  it('lists every nanoparticle handle as an independently selectable endpoint', () => {
    expect(document.getElementById('oconn-np-select')).toBeNull()
    expect(document.getElementById('oconn-np-strand')).toBeNull()
    expect(document.getElementById('oconn-np-overhang')).toBeNull()
    const handles = document.getElementById('oconn-select-a')
    expect([...handles.options].map(option => option.value)).toEqual(['', 's1', 's2'])
    expect(handles.textContent).toContain('NP-1:S1 · applied')
    expect(handles.textContent).toContain('NP-1:S2 · free')
    expect(document.getElementById('oconn-select-b').options[1].value).toBe('oh1_3p')
    expect([...document.querySelectorAll('#oconn-popover .ct-option:not([hidden])')]
      .map(option => option.dataset.variant)).toEqual(['end-to-root', 'root-to-root'])
  })

  it('shows multiple versions with Applied/Unapplied and relaxation residual state', () => {
    const text = document.getElementById('oconn-np-list').textContent
    expect(text).toContain('V1')
    expect(text).toContain('Applied')
    expect(text).toContain('residual 1.25 nm')
    expect(text).toContain('V2')
    expect(text).toContain('Unapplied')
  })

  it('populates existing handle and overhang sequences in the shared rows', () => {
    const target = document.getElementById('oconn-select-b')
    target.value = 'oh1_3p'; target.dispatchEvent(new Event('change'))
    expect(document.getElementById('oconn-seq-input-a').value).toBe('TGCA')
    expect(document.getElementById('oconn-seq-input-b').value).toBe('ACGT')
    expect(document.getElementById('oconn-seq-row-a').hidden).toBe(false)
    expect(document.getElementById('oconn-seq-row-b').hidden).toBe(false)
  })

  it('marks same-root polarity root-to-root as forbidden and prevents selection', () => {
    const target = document.getElementById('oconn-select-b')
    target.value = 'oh1_3p'; target.dispatchEvent(new Event('change'))
    document.getElementById('oconn-button-box').click()
    expect(document.getElementById('oconn-popover').style.gridTemplateColumns).toBe('repeat(2, 188px)')
    const forbidden = document.querySelector('#oconn-popover [data-variant="root-to-root"]')
    expect(forbidden.classList.contains('is-forbidden')).toBe(true)
    expect(forbidden.getAttribute('aria-disabled')).toBe('true')
    expect(forbidden.querySelector('svg').textContent).toContain('!')
    forbidden.dispatchEvent(new Event('click'))
    expect(document.getElementById('oconn-np-add').disabled).toBe(false)
  })

  it('adopts a clicked nanoparticle strand from canonical scene selection', () => {
    store.setState({ selection: { items: [{ kind: 'strand', id: 's2' }] } })
    expect(document.getElementById('oconn-select-a').value).toBe('s2')
  })
})
