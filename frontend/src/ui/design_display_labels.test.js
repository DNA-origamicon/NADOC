import { describe, expect, it } from 'vitest'
import {
  buildStrandDisplayIdMap, helixDisplayLabel, selectedBaseDisplayRows,
} from './design_display_labels.js'

const DESIGN = {
  helices: [
    { id: 'h_XY_0_1', label: null },
    { id: 'h_explicit', label: '45' },
    { id: '__lnk__conn', label: '44' },
  ],
  strands: [
    { id: 'scaf-long', strand_type: 'scaffold', domains: [{ helix_id: 'h_XY_0_1', start_bp: 0, end_bp: 100, direction: 'FORWARD' }] },
    { id: 'stap-a', strand_type: 'staple', domains: [{ helix_id: 'h_XY_0_1', start_bp: 20, end_bp: 50, direction: 'REVERSE' }] },
    { id: 'binder-a', strand_type: 'oh_binder', domains: [{ helix_id: 'h_explicit', start_bp: 90, end_bp: 110, direction: 'FORWARD' }] },
    { id: '__lnk__conn__a', strand_type: 'linker', domains: [{ helix_id: '__lnk__conn', start_bp: 10, end_bp: 22, direction: 'FORWARD' }] },
    { id: 'stap-b', strand_type: 'staple', domains: [] },
  ],
  extensions: [{ id: 'ext-a', strand_id: 'stap-a', end: 'three_prime' }],
  crossovers: [{ id: 'xo-a', half_a: { helix_id: 'h_XY_0_1', index: 43 } }],
}

const GEO = [
  { helix_id: 'h_XY_0_1', bp_index: 34, direction: 'REVERSE', strand_id: 'stap-a', strand_type: 'staple' },
  { helix_id: 'h_XY_0_1', bp_index: 35, direction: 'REVERSE', strand_id: 'stap-a', strand_type: 'staple' },
  { helix_id: 'h_XY_0_1', bp_index: 36, direction: 'REVERSE', strand_id: 'stap-a', strand_type: 'staple' },
  { helix_id: 'h_explicit', bp_index: 104, direction: 'FORWARD', strand_id: 'binder-a', strand_type: 'oh_binder' },
  ...Array.from({ length: 13 }, (_, i) => ({
    helix_id: '__lnk__conn', bp_index: i + 10, direction: 'FORWARD',
    strand_id: '__lnk__conn__a', strand_type: 'linker',
  })),
]

describe('design display labels', () => {
  it('numbers staples, linkers, and every other strand in separate 1-based series', () => {
    expect(Object.fromEntries(buildStrandDisplayIdMap(DESIGN.strands))).toEqual({
      'scaf-long': 'X1', 'stap-a': 'S1', 'binder-a': 'X2',
      '__lnk__conn__a': 'L1', 'stap-b': 'S2',
    })
  })

  it('uses explicit helix labels and otherwise the design helix index', () => {
    expect(helixDisplayLabel(DESIGN, 'h_XY_0_1')).toBe('0')
    expect(helixDisplayLabel(DESIGN, 'h_explicit')).toBe('45')
    expect(helixDisplayLabel(DESIGN, 'missing')).toBe('?')
  })

  it('clusters selected bases by type and compresses runs of three or more', () => {
    const keys = [
      'h_XY_0_1:34:REVERSE', 'h_XY_0_1:35:REVERSE', 'h_XY_0_1:36:REVERSE',
      'h_explicit:104:FORWARD',
      ...Array.from({ length: 13 }, (_, i) => `__lnk__conn:${i + 10}:FORWARD`),
    ]
    expect(selectedBaseDisplayRows(keys, DESIGN, GEO).map(row => row.label)).toEqual([
      'Staple - 0[34-36]', 'OH - 45[104]', 'Linker - 44[10-22]',
    ])
  })

  it('resolves ordinary base roles from design domains when live geometry is rebuilding', () => {
    expect(selectedBaseDisplayRows(['h_XY_0_1:34:REVERSE'], DESIGN).map(row => row.label))
      .toEqual(['Staple - 0[34]'])
  })

  it('keeps bases of one type in one row while separating their helix locations', () => {
    const design = {
      ...DESIGN,
      strands: [...DESIGN.strands, {
        id: 'stap-c', strand_type: 'staple',
        domains: [{ helix_id: 'h_explicit', start_bp: 100, end_bp: 110, direction: 'REVERSE' }],
      }],
    }
    const geometry = [...GEO, {
      helix_id: 'h_explicit', bp_index: 105, direction: 'REVERSE',
      strand_id: 'stap-c', strand_type: 'staple',
    }]
    expect(selectedBaseDisplayRows([
      'h_XY_0_1:34:REVERSE', 'h_explicit:105:REVERSE',
    ], design, geometry).map(row => row.label)).toEqual([
      'Staple - 0[34], 45[105]',
    ])
  })

  it('keeps a two-base pair comma-separated and anchors synthetic base families', () => {
    const keys = [
      'h_XY_0_1:34:REVERSE', 'h_XY_0_1:35:REVERSE',
      '__ext_ext-a:2:REVERSE', '__xb__:xo-a:0',
    ]
    expect(selectedBaseDisplayRows(keys, DESIGN, GEO).map(row => row.label)).toEqual([
      'Staple - 0[34,35]', 'Extension - 0[50›3]', 'Extra base - 0[43+1]',
    ])
  })
})
