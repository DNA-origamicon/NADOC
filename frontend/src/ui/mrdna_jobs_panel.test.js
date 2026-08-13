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
import { initOxdnaFloorSetup } from './oxdna_floor_setup.js'
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

describe('fieldNeedsAnchor (field-drift warning predicate)', () => {
  it('an enabled field with no anchor triggers the drift warning; with ≥1 it is clear', () => {
    expect(fieldNeedsAnchor(true, [])).toBe(true)
    expect(fieldNeedsAnchor(true, null)).toBe(true)
    expect(fieldNeedsAnchor(true, [{ kind: 'strand', id: 's1' }])).toBe(false)
  })
  it('a disabled field never needs an anchor', () => {
    expect(fieldNeedsAnchor(false, [])).toBe(false)
    expect(fieldNeedsAnchor(false, [{ kind: 'strand', id: 's1' }])).toBe(false)
  })
  // M8 deposition exception: a surface the field presses INTO holds it (no anchor).
  it('a field opposed by a hard surface needs no anchor (deposition)', () => {
    const field = { field_pN: 2, dir: [0, -1, 0] }         // field points down (−Y)
    const surfBelow = { dir: [0, 1, 0], offsetNm: 0, stiff: 5 }  // floor below, normal +Y → opposes
    expect(fieldNeedsAnchor(true, [], field, surfBelow)).toBe(false)
    // A surface NOT opposing the field (same side) still drifts → warn.
    const surfAbove = { dir: [0, -1, 0], offsetNm: 0, stiff: 5 } // normal −Y, parallel to field
    expect(fieldNeedsAnchor(true, [], field, surfAbove)).toBe(true)
    // No surface passed → the plain drift condition (warn).
    expect(fieldNeedsAnchor(true, [], field, null)).toBe(true)
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
    setInput(document.getElementById(bag.dirX), 90)     // azimuth
    setInput(document.getElementById(bag.dirY), 0)

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
    const store = createMockStore({ selection: { items: [
      { kind: 'overhang', id: 'o1' },
      { kind: 'overhang', id: 'o2' },
    ] } })
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

// ── M8: hard-surface reachability (PARITY oracle) ─────────────────────────────
// The mrDNA hard-surface BACKEND (M7 ARBD repulsion plane) is already implemented +
// GPU-validated; M8 makes it reachable by mounting the SHARED oxDNA floor card onto
// mrDNA's own DOM ids and threading its {dir, offsetNm, stiff} spec into the create
// body under the cross-engine snake_case key {dir, offset_nm, stiff} — byte-parity with
// the oxDNA production surface request.

describe('buildMrdnaLaunchBody — hard-surface threading', () => {
  it('threads an enabled surface under the snake_case cross-engine key', () => {
    const body = buildMrdnaLaunchBody({
      coarseSteps: 100000, fineSteps: 0, outputPeriod: 10000, device: '0',
      surfaceSpec: { dir: [0, 1, 0], offsetNm: 2.5, stiff: 8 }, surfaceOn: true,
    })
    expect(body.surface).toEqual({ dir: [0, 1, 0], offset_nm: 2.5, stiff: 8 })
  })
  it('omits the surface when disabled or zero-stiff (null, not {})', () => {
    const off = buildMrdnaLaunchBody({
      coarseSteps: 100000, fineSteps: 0, outputPeriod: 10000, device: '0',
      surfaceSpec: { dir: [0, 1, 0], offsetNm: 2, stiff: 8 }, surfaceOn: false,
    })
    expect(off.surface).toBeNull()
    const zero = buildMrdnaLaunchBody({
      coarseSteps: 100000, fineSteps: 0, outputPeriod: 10000, device: '0',
      surfaceSpec: { dir: [0, 1, 0], offsetNm: 2, stiff: 0 }, surfaceOn: true,
    })
    expect(zero.surface).toBeNull()
  })
})

describe('mrDNA launch payload — surface card → body PARITY', () => {
  afterEach(() => clearDom())

  const SURFACE_IDS = {
    'mrdna-surface-toggle': 'div', 'mrdna-surface-arrow': 'span', 'mrdna-surface-body': 'div',
    'mrdna-surface-enable': 'input', 'mrdna-surface-controls': 'div',
    'mrdna-surface-axis': 'select', 'mrdna-surface-offset': 'input',
    'mrdna-surface-offset-label': 'span', 'mrdna-surface-stiff': 'input',
    'mrdna-surface-ready': 'div',
  }
  function mountSurfaceCard() {
    const els = mountIds(SURFACE_IDS)
    for (const [v, label] of [['-y', '−Y (below)'], ['+y', '+Y (above)'], ['-x', '−X']]) {
      const o = document.createElement('option'); o.value = v; o.textContent = label
      els['mrdna-surface-axis'].appendChild(o)
    }
    els['mrdna-surface-stiff'].value = '5'
    els['mrdna-surface-offset'].value = '0'
    return els
  }
  function setInput(el, v) { el.value = String(v); el.dispatchEvent(new Event('input', { bubbles: true })) }

  it('the surface the shared mrDNA card emits is the surface in the launch body', () => {
    const els = mountSurfaceCard()
    const card = initOxdnaFloorSetup({
      ids: {
        toggle: 'mrdna-surface-toggle', arrow: 'mrdna-surface-arrow', body: 'mrdna-surface-body',
        enable: 'mrdna-surface-enable', controls: 'mrdna-surface-controls', axis: 'mrdna-surface-axis',
        offset: 'mrdna-surface-offset', offsetLabel: 'mrdna-surface-offset-label',
        stiff: 'mrdna-surface-stiff', ready: 'mrdna-surface-ready',
      },
    })
    els['mrdna-surface-enable'].checked = true
    els['mrdna-surface-enable'].dispatchEvent(new Event('change', { bubbles: true }))
    els['mrdna-surface-axis'].value = '+y'
    els['mrdna-surface-axis'].dispatchEvent(new Event('change', { bubbles: true }))
    setInput(els['mrdna-surface-offset'], 2.5)
    setInput(els['mrdna-surface-stiff'], 8)

    const spec = card.getSurfaceSpec()
    const body = buildMrdnaLaunchBody({
      coarseSteps: 100000, fineSteps: 0, outputPeriod: 10000, device: '0',
      surfaceSpec: spec, surfaceOn: card.isEnabled(),
    })
    expect(card.isEnabled()).toBe(true)
    expect(body.surface).toEqual({ dir: spec.dir, offset_nm: spec.offsetNm, stiff: spec.stiff })
    expect(body.surface.dir).toEqual([0, -1, 0])   // +y side → normal points down
    expect(body.surface.offset_nm).toBe(2.5)
    expect(body.surface.stiff).toBe(8)
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
