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
  return { store: createMockStore({ currentDesign: null, selection: { items: [] } }) }
})
vi.mock('../api/client.js', () => ({
  deleteHelix: vi.fn(),
  getProteinValidation: vi.fn(),
  repairProteinDuplicate: vi.fn(),
}))

import { store } from '../state/store.js'
import * as api from '../api/client.js'
import { initPropertiesPanel } from './properties_panel.js'

const DESIGN = {
  helices: [{ id: 'h1', label: '1', length_bp: 120 }],
  strands: [
    { id: 'long-scaffold-id', strand_type: 'scaffold',
      domains: [{ helix_id: 'h1', start_bp: 0, end_bp: 119, direction: 'FORWARD' }] },
    { id: 's1', strand_type: 'staple',
      domains: [{ helix_id: 'h1', start_bp: 2, end_bp: 7, direction: 'REVERSE', overhang_id: 'oh1' }] },
  ],
  overhangs: [{ id: 'oh1', strand_id: 's1', label: 'Probe', sequence: 'ACGT' }],
  extensions: [{
    id: 'ext1', strand_id: 's1', end: 'five_prime', sequence: 'TT', modification: 'cy3', label: 'Dye tail',
  }],
  cluster_transforms: [{ id: 'c1', name: 'Hinge', helix_ids: ['h1', 'h2'], is_default: false }],
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

const PROTEIN_SELECTION = {
  items: [{ kind: 'protein', id: 'att1' }],
  primary: { kind: 'protein', id: 'att1' },
}

describe('properties panel — protein branch', () => {
  let content
  beforeEach(() => {
    ;({ 'properties-content': content } = mountIds(['properties-content']))
    store.setState({ currentDesign: null, selection: { items: [] } })
    api.getProteinValidation.mockReset()
    api.repairProteinDuplicate.mockReset()
  })

  it('renders an imported protein without throwing (regression: used to hit _renderNucleotide)', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    expect(() => store._emit({ selection: PROTEIN_SELECTION })).not.toThrow()
    expect(content.innerHTML).toContain('GFP')
  })

  it('shows asset name, source, atom/residue/chain counts, and free anchor', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selection: PROTEIN_SELECTION })
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
    store._emit({ selection: PROTEIN_SELECTION })
    const html = content.innerHTML
    expect(html).toContain('overhang')
    expect(html).toContain('ovhg-7')
    expect(html).toContain('free_end')
  })

  it('falls back gracefully when the attachment is not in the design', () => {
    store.setState({ currentDesign: { protein_assets: [], protein_attachments: [] } })
    initPropertiesPanel()
    expect(() => store._emit({ selection: PROTEIN_SELECTION })).not.toThrow()
    expect(content.innerHTML).toContain('Protein selected')
  })

  it('flags a hidden attachment', () => {
    const d = {
      ...DESIGN,
      protein_attachments: [{ ...DESIGN.protein_attachments[0], visible: false }],
    }
    store.setState({ currentDesign: d })
    initPropertiesPanel()
    store._emit({ selection: PROTEIN_SELECTION })
    expect(content.innerHTML).toContain('hidden')
  })

  it('runs persisted element validation and displays duplicate findings', async () => {
    api.getProteinValidation.mockResolvedValue({
      audit_ms: 12.34,
      elements: [{ attachment_id: 'att1', valid: true, failed_metrics: [] }],
      findings: [{
        code: 'legacy_unconverted_free_placement', asset_id: 'asset1',
        free_attachment_ids: ['att1'], conjugated_attachment_ids: ['att2'],
      }],
    })
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selection: PROTEIN_SELECTION })
    content.querySelector('#protein-validate-btn').click()
    await vi.waitFor(() => expect(content.querySelector('#protein-validation-status').textContent)
      .toContain('legacy_unconverted_free_placement'))
    expect(api.getProteinValidation).toHaveBeenCalledTimes(1)
  })

  it('previews and applies only the audit-proven duplicate repair', async () => {
    api.getProteinValidation.mockResolvedValue({
      elements: [{ attachment_id: 'att1', valid: true, failed_metrics: [] }],
      findings: [{
        code: 'legacy_unconverted_free_placement', asset_id: 'asset1', repairable: true,
        free_attachment_ids: ['att1'], conjugated_attachment_ids: ['att2'],
      }],
    })
    api.repairProteinDuplicate.mockResolvedValue({ applied: true })
    vi.spyOn(globalThis, 'confirm').mockReturnValue(true)
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selection: PROTEIN_SELECTION })
    content.querySelector('#protein-validate-btn').click()
    await vi.waitFor(() => expect(content.querySelector('#protein-repair-duplicate-btn')).not.toBeNull())
    content.querySelector('#protein-repair-duplicate-btn').click()
    await vi.waitFor(() => expect(api.repairProteinDuplicate).toHaveBeenCalledTimes(2))
    expect(api.repairProteinDuplicate.mock.calls).toEqual([
      [{ freeAttachmentId: 'att1', conjugatedAttachmentId: 'att2' }],
      [{ freeAttachmentId: 'att1', conjugatedAttachmentId: 'att2', apply: true }],
    ])
    globalThis.confirm.mockRestore()
  })

  it('renders a canonical overhang ref with its related domain and strand', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selection: { items: [{ kind: 'overhang', id: 'oh1' }] } })
    const html = content.innerHTML
    expect(html).toContain('Probe')
    expect(html).toContain('ACGT')
    expect(html).toContain('#0')
    expect(html).toContain('S1')
  })

  it('renders a canonical extension ref without selectedObject compatibility data', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selection: { items: [{ kind: 'extension', id: 'ext1' }] } })
    const html = content.innerHTML
    expect(html).toContain('Dye tail')
    expect(html).toContain('TT')
    expect(html).toContain('cy3')
    expect(html).toContain('5′')
  })

  it('renders canonical cluster data without selectedObject compatibility state', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selection: { items: [{ kind: 'cluster', id: 'c1' }] } })
    expect(content.innerHTML).toContain('2')
    expect(content.innerHTML).toContain('sub-cluster')
  })

  it('renders the short spreadsheet ID instead of a strand internal id', () => {
    store.setState({ currentDesign: DESIGN })
    initPropertiesPanel()
    store._emit({ selection: { items: [{ kind: 'strand', id: 's1' }] } })
    const firstRow = content.querySelector('.prop-row')
    expect(firstRow.querySelector('.prop-label').textContent).toBe('strand')
    expect(firstRow.querySelector('.prop-val').textContent).toBe('S1')
    expect(content.textContent).not.toContain('s1')
  })

  it('uses helix labels everywhere in strand properties, never internal helix ids', () => {
    const d = {
      ...DESIGN,
      helices: [
        { id: 'h_XY_0_0', label: 3, length_bp: 20 },
        { id: 'h_XY_0_1', label: 4, length_bp: 20 },
      ],
      strands: [{ id: 's1', strand_type: 'staple', domains: [
        { helix_id: 'h_XY_0_0', start_bp: 0, end_bp: 5, direction: 'FORWARD' },
        { helix_id: 'h_XY_0_1', start_bp: 5, end_bp: 10, direction: 'REVERSE' },
      ] }],
    }
    store.setState({ currentDesign: d })
    initPropertiesPanel()
    store._emit({ selection: { items: [{ kind: 'strand', id: 's1' }] } })
    expect(content.textContent).toContain('helices\n        3, 4')
    expect(content.textContent).not.toContain('h_XY_')
  })

  it('clusters canonical base labels by type and helix instead of showing raw keys', () => {
    store.setState({
      currentDesign: DESIGN,
      currentGeometry: [
        { helix_id: 'h1', bp_index: 34, direction: 'REVERSE', strand_id: 's1', strand_type: 'staple' },
        { helix_id: 'h1', bp_index: 35, direction: 'REVERSE', strand_id: 's1', strand_type: 'staple' },
        { helix_id: 'h1', bp_index: 36, direction: 'FORWARD', strand_id: 'long-scaffold-id', strand_type: 'scaffold' },
      ],
    })
    initPropertiesPanel()
    store._emit({ selection: { items: [
      { kind: 'base', key: 'h1:34:REVERSE' },
      { kind: 'base', key: 'h1:35:REVERSE' },
      { kind: 'base', key: 'h1:36:FORWARD' },
    ] } })
    expect(content.textContent).toContain('Staple - 1[34,35]')
    expect(content.textContent).toContain('Scaffold - 1[36]')
    expect(content.textContent).not.toContain('h1:34:REVERSE')
  })

  it('shows a single base, labeled location, and ordinal within its strand', () => {
    store.setState({
      currentDesign: DESIGN,
      currentGeometry: [{
        helix_id: 'h1', bp_index: 4, direction: 'REVERSE', strand_id: 's1',
        strand_type: 'staple', nucleobase: 'A',
      }],
    })
    initPropertiesPanel()
    store._emit({ selection: { items: [{ kind: 'base', key: 'h1:4:REVERSE' }] } })
    const rows = [...content.querySelectorAll('.prop-row')].map(row => [
      row.querySelector('.prop-label')?.textContent,
      row.querySelector('.prop-val')?.textContent,
    ])
    expect(rows).toEqual([
      ['base', 'A'],
      ['location', 'Staple - 1[4]'],
      ['position', '3 in staple S1'],
    ])
  })
})
