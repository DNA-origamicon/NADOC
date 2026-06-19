import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initEfieldSetup } from './efield_setup.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const IDS = {
  'efield-toggle': 'div', 'efield-arrow': 'span', 'efield-body': 'div',
  'efield-mag': 'input',
  'efield-dir-x': 'input', 'efield-dir-y': 'input', 'efield-dir-z': 'input',
  'efield-vpm-toggle': 'div', 'efield-vpm-arrow': 'span', 'efield-vpm-body': 'div',
  'efield-vpm': 'input', 'efield-qeff': 'input', 'efield-vpm-apply': 'button',
  'efield-anchor-add': 'button', 'efield-anchor-clear': 'button',
  'efield-anchors-list': 'div', 'efield-ready': 'div',
  'efield-steps': 'input', 'efield-run-btn': 'button',
}

// api/client.js is dynamically imported; stub the field POST + error reader.
// The POST returns the new CHILD job dict (job_id + status "queued" + efield) —
// exactly what the /field route returns; runField must treat that as success.
vi.mock('../api/client.js', () => ({
  appendOxdnaField: vi.fn(async () => ({
    job_id: 'child999', parent_job_id: 'abcd1234', status: 'queued',
    efield: { force_pN: 2, dir: [0, 0, 1], n_anchored: 1 },
  })),
  lastErrorMessage: () => 'stub error',
}))
import * as apiClient from '../api/client.js'

function makeGizmo() {
  let vec = [0, 1, 0], active = false, onChange = null
  return {
    attach: vi.fn(() => { active = true }),
    detach: vi.fn(() => { active = false }),
    setVector: vi.fn((v) => { vec = v.slice() }),
    getVector: () => vec.slice(),
    setOnChange: (cb) => { onChange = cb },
    setColor: vi.fn(),
    isActive: () => active,
    _fireDrag: (v) => onChange?.(v),   // test hook: simulate a tip drag
  }
}

function setInput(el, value) {
  el.value = String(value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('initEfieldSetup', () => {
  let els, store, gizmo, api, selectedJob, onRan

  beforeEach(() => {
    els = mountIds(IDS)
    store = createMockStore({ multiSelectedOverhangIds: [], multiSelectedDomainIds: [], selectedObject: null })
    gizmo = makeGizmo()
    selectedJob = null
    onRan = vi.fn()
    apiClient.appendOxdnaField.mockClear()
    api = initEfieldSetup({
      store, gizmo, getSelection: () => store.getState(),
      getSelectedJob: () => selectedJob, onRan,
    })
  })
  afterEach(() => clearDom())

  it('starts collapsed; opening attaches the gizmo', () => {
    expect(els['efield-body'].style.display).toBe('none')
    expect(gizmo.attach).not.toHaveBeenCalled()
    els['efield-toggle'].click()
    expect(els['efield-body'].style.display).toBe('')
    expect(gizmo.attach).toHaveBeenCalled()
    els['efield-toggle'].click()
    expect(els['efield-body'].style.display).toBe('none')
    expect(gizmo.detach).toHaveBeenCalled()
  })

  it('magnitude input drives the gizmo and the field spec', () => {
    els['efield-toggle'].click()
    setInput(els['efield-mag'], 2.5)
    expect(api.getFieldSpec().field_pN).toBe(2.5)
    expect(gizmo.setVector).toHaveBeenCalled()
  })

  it('direction inputs feed a normalized dir into the spec', () => {
    setInput(els['efield-dir-x'], 0)
    setInput(els['efield-dir-y'], 0)
    setInput(els['efield-dir-z'], 5)
    const spec = api.getFieldSpec()
    expect(spec.dir[2]).toBeCloseTo(1)
  })

  it('V/m helper computes force-per-nucleotide into the pN field', () => {
    els['efield-toggle'].click()
    els['efield-qeff'].value = '0.25'
    els['efield-vpm'].value = '1000000'   // 1e6 V/m
    els['efield-vpm-apply'].click()
    expect(api.getFieldSpec().field_pN).toBeCloseTo(0.0400544, 5)
  })

  it('Add anchor reads the current selection; ready gate needs force + dir + anchor', () => {
    els['efield-toggle'].click()
    setInput(els['efield-mag'], 1)
    // no anchor yet → not ready
    expect(els['efield-ready'].textContent).toMatch(/Not ready/)

    store.setState({ multiSelectedOverhangIds: ['o1', 'o2'] })
    const added = api.addSelectedAnchors()
    expect(added).toBe(2)
    expect(api.getAnchors().map(a => a.id).sort()).toEqual(['o1', 'o2'])
    // Spec is now complete; without a selected job the gate asks for one.
    expect(els['efield-ready'].textContent).not.toMatch(/Not ready/)
    expect(els['efield-ready'].textContent).toMatch(/Field set|Ready/)
  })

  it('Add with nothing selected warns and adds nothing', () => {
    els['efield-toggle'].click()
    const added = api.addSelectedAnchors()
    expect(added).toBe(0)
    expect(api.getAnchors()).toHaveLength(0)
    expect(els['efield-ready'].textContent).toMatch(/Select an overhang/)
  })

  it('a chip remove ✕ drops that anchor', () => {
    els['efield-toggle'].click()
    store.setState({ multiSelectedOverhangIds: ['o1', 'o2'] })
    api.addSelectedAnchors()
    const x = els['efield-anchors-list'].querySelector('[data-key="overhang:o1"] span:last-child')
    x.click()
    expect(api.getAnchors().map(a => a.id)).toEqual(['o2'])
  })

  it('Clear removes all anchors', () => {
    els['efield-toggle'].click()
    store.setState({ multiSelectedOverhangIds: ['o1'] })
    api.addSelectedAnchors()
    els['efield-anchor-clear'].click()
    expect(api.getAnchors()).toHaveLength(0)
  })

  it('a gizmo drag updates the magnitude (length → pN)', () => {
    els['efield-toggle'].click()
    gizmo._fireDrag([0, 10, 0])   // 10 nm arrow → (10-2)/4 = 2 pN
    expect(api.getFieldSpec().field_pN).toBeCloseTo(2, 6)
    expect(els['efield-mag'].value).toBe('2')
  })

  // ── Run field (panel↔efield handoff) ─────────────────────────────────────
  function makeRunnable() {
    els['efield-toggle'].click()
    setInput(els['efield-mag'], 2)
    setInput(els['efield-dir-x'], 0)
    setInput(els['efield-dir-y'], 0)
    setInput(els['efield-dir-z'], 1)
    store.setState({ multiSelectedOverhangIds: ['o1'] })
    api.addSelectedAnchors()
  }

  it('Run button is disabled until field is ready AND a completed job is selected', () => {
    makeRunnable()
    // ready spec but no job → disabled
    expect(els['efield-run-btn'].disabled).toBe(true)
    expect(els['efield-ready'].textContent).toMatch(/select a completed oxDNA job/i)
    // a still-running job → disabled
    selectedJob = { job_id: 'abcd1234', status: 'running' }
    api.refresh()
    expect(els['efield-run-btn'].disabled).toBe(true)
    // completed job → enabled
    selectedJob = { job_id: 'abcd1234', status: 'completed' }
    api.refresh()
    expect(els['efield-run-btn'].disabled).toBe(false)
    expect(els['efield-ready'].textContent).toMatch(/Ready/)
  })

  it('Run posts the field spec to the selected completed job and refreshes the panel', async () => {
    makeRunnable()
    selectedJob = { job_id: 'abcd1234', status: 'completed' }
    api.refresh()
    const ok = await api.runField()
    expect(ok).toBe(true)
    expect(apiClient.appendOxdnaField).toHaveBeenCalledTimes(1)
    const [jobId, body] = apiClient.appendOxdnaField.mock.calls[0]
    expect(jobId).toBe('abcd1234')
    expect(body.field_pN).toBe(2)
    expect(body.dir[2]).toBeCloseTo(1)
    expect(body.anchors.map(a => a.id)).toEqual(['o1'])
    expect(onRan).toHaveBeenCalled()
  })

  it('Run is a no-op when the field is not ready (no anchor)', async () => {
    els['efield-toggle'].click()
    setInput(els['efield-mag'], 2)
    selectedJob = { job_id: 'abcd1234', status: 'completed' }
    const ok = await api.runField()
    expect(ok).toBe(false)
    expect(apiClient.appendOxdnaField).not.toHaveBeenCalled()
  })

  it('reacts to the panel selection event — Run enables when a completed parent is selected', () => {
    makeRunnable()
    expect(els['efield-run-btn'].disabled).toBe(true)                 // no job selected yet
    selectedJob = { job_id: 'parent1', status: 'completed' }
    window.dispatchEvent(new CustomEvent('nadoc:oxdna-job-selected')) // panel notifies on click
    expect(els['efield-run-btn'].disabled).toBe(false)               // Run enabled, no hover needed
    expect(els['efield-ready'].textContent).toMatch(/Ready/)
  })

  it('runField is a no-op on a field child even if invoked directly (defensive)', async () => {
    makeRunnable()
    selectedJob = { job_id: 'c', status: 'completed', parent_job_id: 'p' }
    const ok = await api.runField()
    expect(ok).toBe(false)
    expect(apiClient.appendOxdnaField).not.toHaveBeenCalled()
  })

  it('a completed FIELD child cannot itself be branched (must pick the relaxed parent)', () => {
    makeRunnable()
    selectedJob = { job_id: 'child999', status: 'completed', parent_job_id: 'abcd1234' }
    api.refresh()
    expect(els['efield-run-btn'].disabled).toBe(true)
    expect(els['efield-ready'].textContent).toMatch(/parent relaxed job/i)
  })

  it('magnitude grades the gizmo colour and warns when strong enough to disrupt', () => {
    els['efield-toggle'].click()
    setInput(els['efield-mag'], 5)
    expect(gizmo.setColor).toHaveBeenCalled()
    setInput(els['efield-mag'], 100)            // ≥ disrupt threshold
    store.setState({ multiSelectedOverhangIds: ['o1'] })
    api.addSelectedAnchors()
    expect(els['efield-ready'].textContent).toMatch(/disrupt/i)
  })
})
