// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import {
  formatProgress,
  jobDisplayName,
  mrdnaJobIsActive,
  detailStatusText,
  coarseStageChip,
  formatCurvature,
  seedReady,
  fieldNeedsAnchor,
  buildMrdnaLaunchBody,
} from './mrdna_jobs_panel.js'
import { initForcesCard, FORCES_FIELD_IDS } from './forces_card.js'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

describe('seedReady', () => {
  it('is true only for a completed FINE-stage job', () => {
    expect(seedReady({ status: 'completed', fine_steps: 10000 })).toBe(true)
    expect(seedReady({ status: 'completed', fine_steps: 0 })).toBe(false)   // coarse-only
    expect(seedReady({ status: 'completed' })).toBe(false)                  // no fine
    expect(seedReady({ status: 'running', fine_steps: 10000 })).toBe(false)
    expect(seedReady(null)).toBe(false)
  })
})

describe('formatProgress', () => {
  it('is 100% when completed, blank when failed/stopped', () => {
    expect(formatProgress({ status: 'completed' })).toBe('100%')
    expect(formatProgress({ status: 'failed' })).toBe('')
    expect(formatProgress({ status: 'stopped' })).toBe('')
  })
  it('rounds the running overall fraction', () => {
    expect(formatProgress({ status: 'running' }, { overall: 0.42 })).toBe('42%')
    expect(formatProgress({ status: 'running' }, { overall: 0 })).toBe('…')
  })
})

describe('jobDisplayName', () => {
  it('prefers the source-path stem', () => {
    expect(jobDisplayName({ design_source_path: 'a/b/6hb_test.nadoc', design_name: 'x' }))
      .toBe('6hb_test')
  })
  it('falls back to design_name', () => {
    expect(jobDisplayName({ design_name: 'mydesign' })).toBe('mydesign')
    expect(jobDisplayName({})).toBe('design')
  })
})

describe('mrdnaJobIsActive', () => {
  it('is true for queued/preparing/running only', () => {
    for (const s of ['queued', 'preparing', 'running']) {
      expect(mrdnaJobIsActive({ status: s })).toBe(true)
    }
    for (const s of ['completed', 'failed', 'stopped']) {
      expect(mrdnaJobIsActive({ status: s })).toBe(false)
    }
  })
})

describe('detailStatusText', () => {
  it('shows an ETA while running', () => {
    const t = detailStatusText({ status: 'running' }, { overall: 0.5, eta_seconds: 12 })
    expect(t).toContain('50%')
    expect(t).toContain('12s left')
  })
  it('summarises a completed run', () => {
    const t = detailStatusText({ status: 'completed', sim_seconds: 8.4, n_beads: 635 })
    expect(t).toContain('8.4s')
    expect(t).toContain('635 CG beads')
  })
  it('surfaces the failure message', () => {
    expect(detailStatusText({ status: 'failed', error: 'boom' })).toContain('boom')
  })
})

describe('coarseStageChip', () => {
  it('glyphs each stage (coarse, and fine when present)', () => {
    expect(coarseStageChip({ stages: [{ name: 'coarse', status: 'done' }] })).toBe('● coarse')
    expect(coarseStageChip({ stages: [{ name: 'coarse', status: 'running' }] })).toBe('◐ coarse')
    expect(coarseStageChip({ stages: [{ name: 'coarse', status: 'failed' }] })).toBe('✗ coarse')
    expect(coarseStageChip({})).toBe('○ coarse')
    expect(coarseStageChip({ stages: [
      { name: 'coarse', status: 'done' }, { name: 'fine', status: 'running' }] }))
      .toBe('● coarse  ◐ fine')
  })
})

// ── M6: E-field + Anchors reachability (PARITY oracle) ────────────────────────
// The mrDNA field/anchor BACKENDS (M1/M2) are already implemented + tested; M6 makes
// them reachable from the panel by mounting the SHARED Forces + Anchors cards and
// threading their output into the create body. The bright line: the launch payload
// carries the SAME {field_pN, dir} the shared card emits + the SAME anchor list the
// shared Anchors card emits (byte-parity with CanDo/oxDNA/NAMD).

describe('fieldNeedsAnchor (field-drift guard)', () => {
  it('an enabled field with no anchor is blocked; with ≥1 it is allowed', () => {
    expect(fieldNeedsAnchor(true, [])).toBe(true)
    expect(fieldNeedsAnchor(true, null)).toBe(true)
    expect(fieldNeedsAnchor(true, [{ kind: 'strand', id: 's1' }])).toBe(false)
  })
  it('a disabled field never needs an anchor', () => {
    expect(fieldNeedsAnchor(false, [])).toBe(false)
    expect(fieldNeedsAnchor(false, [{ kind: 'strand', id: 's1' }])).toBe(false)
  })
})

describe('buildMrdnaLaunchBody (payload threading)', () => {
  it('threads an enabled field + anchors under the shared keys', () => {
    const body = buildMrdnaLaunchBody({
      coarseSteps: 5000, fineSteps: 0, outputPeriod: 2000, device: '1', sourcePath: 'w/x.nadoc',
      anchors: [{ kind: 'strand', id: 's1' }], fieldSpec: { field_pN: 2.5, dir: [0, 1, 0] }, fieldOn: true,
    })
    expect(body.field).toEqual({ field_pN: 2.5, dir: [0, 1, 0] })
    expect(body.anchors).toEqual([{ kind: 'strand', id: 's1' }])
    expect(body).toMatchObject({
      coarse_steps: 5000, fine_steps: 0, output_period: 2000, device: '1',
      autostart: true, design_source_path: 'w/x.nadoc',
    })
  })
  it('omits the field when disabled and anchors when empty (null, not [])', () => {
    const body = buildMrdnaLaunchBody({
      coarseSteps: 100000, fineSteps: 200000, outputPeriod: 10000, device: '0',
      anchors: [], fieldSpec: { field_pN: 3, dir: [1, 0, 0] }, fieldOn: false,
    })
    expect(body.field).toBeNull()
    expect(body.anchors).toBeNull()
  })
  it('clamps step/period floors and defaults the device', () => {
    const body = buildMrdnaLaunchBody({ coarseSteps: 10, outputPeriod: 1, device: '  ', fineSteps: 0 })
    expect(body.coarse_steps).toBe(1000)     // min 1000
    expect(body.output_period).toBe(100)     // min 100
    expect(body.device).toBe('0')            // blank → '0'
    expect(body.design_source_path).toBeNull()
  })
})

describe('mrDNA launch payload — card → body PARITY', () => {
  afterEach(() => clearDom())

  // id→tag map for a field card, from the engine's shared id bag (mirrors forces_card.test).
  function fieldTags(engine) {
    const bag = FORCES_FIELD_IDS[engine]
    const tags = {}
    for (const [k, id] of Object.entries(bag)) {
      tags[id] = (k === 'toggle' || k === 'body' || k === 'vpmBody') ? 'div'
        : (k === 'vpmApply') ? 'button'
        : (k === 'arrow' || k === 'vpmArrow' || k === 'ready') ? 'span' : 'input'
    }
    return tags
  }
  function setInput(el, v) { el.value = String(v); el.dispatchEvent(new Event('input', { bubbles: true })) }

  it('the field the shared mrDNA card emits is the field in the launch body', () => {
    const bag = FORCES_FIELD_IDS.mrdna
    mountIds(fieldTags('mrdna'))
    const card = initForcesCard({ engine: 'mrdna' })     // numeric (no gizmo), like CanDo/NAMD
    const chk = document.getElementById(bag.enable)
    chk.checked = true; chk.dispatchEvent(new Event('change', { bubbles: true }))
    setInput(document.getElementById(bag.mag), 1.8)
    setInput(document.getElementById(bag.dirX), 0)
    setInput(document.getElementById(bag.dirY), 0)
    setInput(document.getElementById(bag.dirZ), 3)       // normalizes to [0,0,1]

    const spec = card.getFieldSpec()
    const body = buildMrdnaLaunchBody({
      coarseSteps: 100000, fineSteps: 0, outputPeriod: 10000, device: '0',
      anchors: [], fieldSpec: spec, fieldOn: card.isEnabled(),
    })
    expect(card.isEnabled()).toBe(true)
    expect(body.field).toEqual({ field_pN: spec.field_pN, dir: spec.dir })
    expect(body.field.field_pN).toBe(1.8)
    expect(body.field.dir.map(x => +x.toFixed(6))).toEqual([0, 0, 1])
  })

  it('the anchor list the shared Anchors card holds is the anchors in the launch body', () => {
    mountIds({
      'mrdna-anchors-toggle': 'div', 'mrdna-anchors-arrow': 'span', 'mrdna-anchors-body': 'div',
      'mrdna-anchors-add': 'button', 'mrdna-anchors-clear': 'button',
      'mrdna-anchors-list': 'div', 'mrdna-anchors-status': 'div',
    })
    const store = createMockStore({ multiSelectedOverhangIds: ['o1', 'o2'], multiSelectedDomainIds: [], selectedObject: null })
    const anchorsCard = initOxdnaAnchorsSetup({
      getSelection: () => store.getState(),
      ids: {
        toggle: 'mrdna-anchors-toggle', arrow: 'mrdna-anchors-arrow', body: 'mrdna-anchors-body',
        add: 'mrdna-anchors-add', clear: 'mrdna-anchors-clear', list: 'mrdna-anchors-list',
        status: 'mrdna-anchors-status',
      },
    })
    expect(anchorsCard.addSelectedAnchors()).toBe(2)
    const anchors = anchorsCard.getAnchors()
    const body = buildMrdnaLaunchBody({
      coarseSteps: 100000, fineSteps: 0, outputPeriod: 10000, device: '0',
      anchors, fieldSpec: null, fieldOn: false,
    })
    expect(body.anchors).toEqual(anchors)
    expect(body.anchors.map(a => a.id).sort()).toEqual(['o1', 'o2'])
  })
})

describe('formatCurvature', () => {
  const analytic = { has_marks: true, radius_nm: 36, kappa_deg_per_nm: 1.58, bend_deg: 88 }

  it('says nothing to bend when the design has no marks', () => {
    expect(formatCurvature({ analytic: { has_marks: false } })).toMatch(/nothing to bend/)
    expect(formatCurvature(null)).toMatch(/nothing to bend/)
  })
  it('shows the designed curvature', () => {
    const html = formatCurvature({ analytic, measured: null })
    expect(html).toMatch(/Designed/)
    expect(html).toMatch(/36 nm/)
    expect(html).toMatch(/88°/)
  })
  it('nudges to run Fine when the run was coarse-only', () => {
    const html = formatCurvature({ analytic, measured: { radius_nm: 300, bend_deg: 3 }, fine: false })
    expect(html).toMatch(/Coarse run/)
    expect(html).toMatch(/Run <b>Fine<\/b>/)
  })
  it('shows simulated vs designed with a ratio for a fine run', () => {
    const html = formatCurvature({
      analytic, measured: { radius_nm: 45, bend_deg: 70 }, fine: true, ratio: 0.8 })
    expect(html).toMatch(/Simulated/)
    expect(html).toMatch(/45 nm/)
    expect(html).toMatch(/80% of designed/)
  })
  it('flags the CG under-reproduction caveat on a low ratio', () => {
    const html = formatCurvature({
      analytic, measured: { radius_nm: 900, bend_deg: 4 }, fine: true, ratio: 0.05 })
    expect(html).toMatch(/under-reproduces loop\/skip curvature/)
    expect(html).toMatch(/5% of designed/)
  })
  it('formats a straight (infinite-radius) measurement', () => {
    const html = formatCurvature({
      analytic, measured: { radius_nm: Infinity, bend_deg: 1 }, fine: true, ratio: null })
    expect(html).toMatch(/straight/)
  })
})
