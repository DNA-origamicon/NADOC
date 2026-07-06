/**
 * Tests for the cross-engine "Shape comparison" card (S5).
 *
 * Two layers: (1) the PURE view-model / CSV / chart-spec helpers derive the right numbers
 * from a `build_comparison_report`-shaped payload; (2) the factory wiring — Generate →
 * poll → render populates the tables + overlay, and an empty source list reports the
 * not-ready state without starting a run.  jsdom DOM (the card ids) + mocked api client.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const start = vi.fn()
const poll = vi.fn()

import {
  fmtNum, fmtDelta, scalarTableModel, rmsfOverlaySpec, comparisonCSVs,
  initShapeCompareCard, SCALAR_LABELS,
} from './shape_compare_card.js'

function makeReport() {
  return {
    ready: true,
    engines: ['oxdna', 'cando'],
    references: { shape: 'oxdna', rmsf: 'cando', field: 'oxdna' },
    scalars: [
      { name: 'twist_total_deg', reference: 'oxdna',
        cells: { oxdna: { value: 100, signed_pct_delta: null },
                 cando: { value: 110, signed_pct_delta: 10 } } },
      { name: 'bend_angle_deg', reference: 'oxdna',
        cells: { oxdna: { value: 20, signed_pct_delta: null },
                 cando: { value: 15, signed_pct_delta: -25 } } },
    ],
    rmsf_profiles: [
      { engine: 'cando', is_reference: true, points: [[0, 1], [1, 2], [2, 3]] },
      { engine: 'oxdna', is_reference: false, points: [[0, 1.1], [1, 1.9], [2, 3.2]] },
    ],
    agreement: [
      { engine: 'cando', shape_rmsd_nm: 0.5,
        rmsf: null, field: null },
      { engine: 'oxdna', shape_rmsd_nm: null,
        rmsf: { pearson: 0.98, spearman: 0.95, n: 3 }, field: null },
    ],
    field: {
      reference: 'oxdna',
      rows: [
        { engine: 'oxdna', is_reference: true, anchored_max_drift_nm: 0.2,
          free_proj_along_field_nm: 2.0, passed: true, cosine_vs_ref: null, magnitude_ratio: null },
        { engine: 'cando', is_reference: false, anchored_max_drift_nm: 0.3,
          free_proj_along_field_nm: 6.0, passed: true, cosine_vs_ref: 1.0, magnitude_ratio: 3.0 },
      ],
    },
  }
}

describe('pure helpers', () => {
  it('fmtNum / fmtDelta handle null + sign', () => {
    expect(fmtNum(1.2345, 2)).toBe('1.23')
    expect(fmtNum(null)).toBe('—')
    expect(fmtNum(Infinity)).toBe('—')
    expect(fmtDelta(3.14)).toBe('+3.1%')
    expect(fmtDelta(-25)).toBe('-25.0%')
    expect(fmtDelta(null)).toBe('—')
  })

  it('scalarTableModel keeps engine column order + flags the reference', () => {
    const m = scalarTableModel(makeReport())
    expect(m.engines).toEqual(['oxdna', 'cando'])
    expect(m.reference).toBe('oxdna')
    const twist = m.rows.find(r => r.name === 'twist_total_deg')
    expect(twist.label).toBe(SCALAR_LABELS.twist_total_deg)
    expect(twist.cells.map(c => c.engine)).toEqual(['oxdna', 'cando'])
    expect(twist.cells[0].isReference).toBe(true)
    expect(twist.cells[1].deltaPct).toBe(10)
  })

  it('rmsfOverlaySpec builds one series per engine, reference first', () => {
    const spec = rmsfOverlaySpec(makeReport(), { width: 400, height: 200 })
    expect(spec.empty).toBe(false)
    expect(spec.series).toHaveLength(2)
    expect(spec.series[0].label).toBe('cando (ref)')   // reference sorted first
    expect(spec.series[1].label).toBe('oxdna')
  })

  it('rmsfOverlaySpec is empty when no profiles', () => {
    const spec = rmsfOverlaySpec({ engines: [], rmsf_profiles: [] })
    expect(spec.empty).toBe(true)
  })

  it('comparisonCSVs emits scalar, agreement + field sections with the right numbers', () => {
    const csv = comparisonCSVs(makeReport())
    expect(csv.scalars).toContain('# shape reference: oxdna')
    expect(csv.scalars).toContain('descriptor,oxdna,oxdna_pct_vs_ref,cando,cando_pct_vs_ref')
    expect(csv.scalars).toContain('twist_total_deg,100,,110,10')
    expect(csv.agreement).toContain('engine,shape_rmsd_nm,rmsf_pearson')
    expect(csv.agreement).toContain('cando,0.5,')
    expect(csv.agreement).toContain('oxdna,,0.98,0.95,3')
    expect(csv.field).toContain('# field reference: oxdna')
    expect(csv.field).toContain('cando,0,0.3,6,1,1,3')
  })

  it('comparisonCSVs omits the field section when no field data', () => {
    const r = makeReport(); r.field = null
    expect(comparisonCSVs(r).field).toBe('')
  })
})

const IDS = {
  'shape-compare-card': 'div',
  'shape-compare-toggle': 'div',
  'shape-compare-arrow': 'span',
  'shape-compare-gen': 'button',
  'shape-compare-export': 'button',
  'shape-compare-bar': 'div',
  'shape-compare-fill': 'div',
  'shape-compare-status': 'div',
  'shape-compare-scalars': 'div',
  'shape-compare-agreement': 'div',
  'shape-compare-field': 'div',
  'shape-compare-rmsf': 'canvas',
}

beforeEach(() => {
  clearDom(); mountIds(IDS)
  start.mockReset(); poll.mockReset()
})

describe('initShapeCompareCard wiring', () => {
  it('Generate with sources → poll → render fills tables + enables Export', async () => {
    start.mockResolvedValue({ metrics_id: 'r1', state: 'running' })
    poll.mockResolvedValue({ state: 'done', progress: 1, result: makeReport() })
    const card = initShapeCompareCard({
      api: { start: (...a) => start(...a), poll: (...a) => poll(...a) },
      getSources: () => [{ engine: 'oxdna' }, { engine: 'cando' }],
    })
    await card._generate()
    await new Promise(r => setTimeout(r, 0))   // let the poll tick resolve
    expect(start).toHaveBeenCalledOnce()
    const scalars = document.getElementById('shape-compare-scalars').innerHTML
    expect(scalars).toContain('Twist total')
    expect(scalars).toContain('+10.0%')
    const field = document.getElementById('shape-compare-field').innerHTML
    expect(field).toContain('E-field deflection')
    expect(document.getElementById('shape-compare-export').disabled).toBe(false)
  })

  it('Generate with no sources reports not-ready and never starts a run', async () => {
    const card = initShapeCompareCard({
      api: { start: (...a) => start(...a), poll: (...a) => poll(...a) },
      getSources: () => [],
    })
    await card._generate()
    expect(start).not.toHaveBeenCalled()
    expect(document.getElementById('shape-compare-status').textContent)
      .toContain('No engine predictions available')
    expect(document.getElementById('shape-compare-export').disabled).toBe(true)
  })

  it('refresh clears the rendered tables + disables Export', async () => {
    start.mockResolvedValue({ metrics_id: 'r1', state: 'running' })
    poll.mockResolvedValue({ state: 'done', progress: 1, result: makeReport() })
    const card = initShapeCompareCard({
      api: { start: (...a) => start(...a), poll: (...a) => poll(...a) },
      getSources: () => [{ engine: 'oxdna' }, { engine: 'cando' }],
    })
    await card._generate()
    await new Promise(r => setTimeout(r, 0))
    card.refresh()
    expect(document.getElementById('shape-compare-scalars').innerHTML).toBe('')
    expect(document.getElementById('shape-compare-export').disabled).toBe(true)
  })
})
