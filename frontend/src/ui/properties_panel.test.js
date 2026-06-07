/**
 * Tests for the properties panel's protein branch (added after the #85 protein
 * subsystem extraction surfaced that selecting a {type:'protein'} object threw
 * — the panel had no protein branch and fell through to _renderNucleotide).
 *
 * The panel imports the singleton store + api modules directly, so we mock them.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

vi.mock('../state/store.js', async () => {
  const { createMockStore } = await import('../test-helpers/mock_store.js')
  return { store: createMockStore({ currentDesign: null, selectedObject: null }) }
})
vi.mock('../api/client.js', () => ({ deleteHelix: vi.fn() }))

import { store } from '../state/store.js'
import { initPropertiesPanel } from './properties_panel.js'

const DESIGN = {
  protein_assets: [{
    id: 'asset1',
    name: 'GFP',
    source_filename: 'gfp.pdb',
    atoms: new Array(1820).fill(0).map((_, i) => ({ serial: i })),
    metadata: { residue_count: 230, chain_ids: ['A', 'B'] },
  }],
  protein_attachments: [{
    id: 'att1',
    asset_id: 'asset1',
    target: { kind: 'free' },
    conjugation_atom_serial: 42,
    handle_complement_bp: 0,
    handle_spacer_nt: 0,
    visible: true,
  }],
}

const PROTEIN_SEL = { type: 'protein', id: 'att1', data: { attachment_id: 'att1' } }

describe('properties panel — protein branch', () => {
  let content
  beforeEach(() => {
    ;({ 'properties-content': content } = mountIds(['properties-content']))
    store.setState({ currentDesign: null, selectedObject: null })
  })

  it('renders an imported protein without throwing (regression: used to hit _renderNucleotide)', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    expect(() => store._emit({ selectedObject: PROTEIN_SEL })).not.toThrow()
    expect(content.innerHTML).toContain('GFP')
  })

  it('shows asset name, source, atom/residue/chain counts, and free anchor', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selectedObject: PROTEIN_SEL })
    const html = content.innerHTML
    expect(html).toContain('GFP')
    expect(html).toContain('gfp.pdb')
    expect(html).toContain('1820')           // atom count
    expect(html).toContain('230')            // residue count
    expect(html).toContain('A, B')           // chain ids
    expect(html).toContain('free')           // anchor kind
    expect(html).toContain('serial 42')      // conjugation atom
  })

  it('renders the overhang anchor with overhang id + attach end', () => {
    const d = {
      ...DESIGN,
      protein_attachments: [{
        ...DESIGN.protein_attachments[0],
        target: { kind: 'overhang', overhang_id: 'ovhg-7', attach_end: 'free_end' },
      }],
    }
    store.setState({ currentDesign: d })
    initPropertiesPanel()
    store._emit({ selectedObject: PROTEIN_SEL })
    const html = content.innerHTML
    expect(html).toContain('overhang')
    expect(html).toContain('ovhg-7')
    expect(html).toContain('free_end')
  })

  it('falls back gracefully when the attachment is not in the design', () => {
    store.setState({ currentDesign: { protein_assets: [], protein_attachments: [] } })
    initPropertiesPanel()
    expect(() => store._emit({ selectedObject: PROTEIN_SEL })).not.toThrow()
    expect(content.innerHTML).toContain('Protein selected')
  })

  it('flags a hidden attachment', () => {
    const d = {
      ...DESIGN,
      protein_attachments: [{ ...DESIGN.protein_attachments[0], visible: false }],
    }
    store.setState({ currentDesign: d })
    initPropertiesPanel()
    store._emit({ selectedObject: PROTEIN_SEL })
    expect(content.innerHTML).toContain('hidden')
  })
})
