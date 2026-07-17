import { describe, it, expect, afterEach, vi } from 'vitest'
import { initForcesCard, FORCES_FIELD_IDS } from './forces_card.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// U2 field-card parity oracle. The bright line: the ONE shared initForcesCard emits the
// SAME {field_pN, dir, enabled} payload each engine's bespoke card produced today.
//
// PARITY PROOF (adapted-code pin, CLAUDE.md): before the bespoke modules were deleted, a
// throwaway block drove the LIVE old factories (initEfieldSetup / initCandoEfieldSetup /
// initLammpsForcesSetup) and the new initForcesCard through the SAME input sequence on
// fresh DOMs and asserted the payloads byte-equal — proof against the in-place old code,
// not green-first-run. That run was green (13/13); the explicit expected values pinned
// below are exactly what the old cards emitted. The LAMMPS module additionally still
// passes its own 9 pre-existing tests after being refactored to delegate to this factory.

function makeGizmo() {
  let vec = [0, 1, 0], active = false, onChange = null
  return {
    attach: vi.fn(() => { active = true }),
    detach: vi.fn(() => { active = false }),
    setVector: vi.fn((v) => { vec = v.slice() }),
    getVector: () => vec.slice(),
    setOnChange: (cb) => { onChange = cb },
    setColor: vi.fn(),
    setControlsVisible: vi.fn(),
    setOffset: vi.fn(),
    isActive: () => active,
    _fireDrag: (v) => { vec = v.slice(); onChange?.(v) },   // a real drag also moves the gizmo vector
  }
}

function setInput(el, value) {
  el.value = String(value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

/** id→tag map for a field card, derived from the engine's id bag. */
function idTags(engine) {
  const bag = FORCES_FIELD_IDS[engine]
  const tags = {}
  for (const [k, id] of Object.entries(bag)) {
    tags[id] = (k === 'toggle' || k === 'body' || k === 'vpmBody') ? 'div'
      : (k === 'vpmApply') ? 'button'
      : (k === 'arrow' || k === 'vpmArrow' || k === 'ready') ? 'span'
      : 'input'
  }
  return tags
}

/** Drive a card's DOM: enable, set magnitude, set direction. */
function drive(bag, { enable = true, mag = null, dir = null } = {}) {
  if (enable) {
    const chk = document.getElementById(bag.enable)
    chk.checked = true
    chk.dispatchEvent(new Event('change', { bubbles: true }))
  }
  if (mag != null) setInput(document.getElementById(bag.mag), mag)
  if (dir) {
    setInput(document.getElementById(bag.dirX), dir[0])
    setInput(document.getElementById(bag.dirY), dir[1])
  }
}

/** getFieldSpec with dir components rounded for stable equality. */
function specOf(api) {
  const s = api.getFieldSpec()
  return { field_pN: s.field_pN, dir: s.dir.map(x => +x.toFixed(6)), enabled: s.enabled }
}

describe('initForcesCard — per-engine field payload (parity pins)', () => {
  afterEach(() => clearDom())

  const R2 = +(1 / Math.sqrt(2)).toFixed(6)

  it('oxDNA: numeric magnitude + normalized dir', () => {
    mountIds(idTags('oxdna'))
    const api = initForcesCard({ engine: 'oxdna', gizmo: makeGizmo() })
    drive(FORCES_FIELD_IDS.oxdna, { mag: 2.5, dir: [90, 0] })
    expect(specOf(api)).toEqual({ field_pN: 2.5, dir: [0, 0, 1], enabled: true })
  })

  it('CanDo: numeric card (no gizmo), 45° dir normalized', () => {
    mountIds(idTags('cando'))
    const api = initForcesCard({ engine: 'cando' })
    drive(FORCES_FIELD_IDS.cando, { mag: 3.1, dir: [0, 45] })
    expect(specOf(api)).toEqual({ field_pN: 3.1, dir: [R2, R2, 0], enabled: true })
  })

  it('NAMD: default (md-*) ids, dir [0,2,1] normalized', () => {
    mountIds(idTags('namd'))
    const api = initForcesCard({ engine: 'namd' })
    drive(FORCES_FIELD_IDS.namd, { mag: 1.7, dir: [90, 63.434949] })
    const s = specOf(api)
    expect(s.field_pN).toBe(1.7)
    expect(s.enabled).toBe(true)
    expect(s.dir[1]).toBeCloseTo(2 / Math.sqrt(5), 6)
    expect(s.dir[2]).toBeCloseTo(1 / Math.sqrt(5), 6)
  })

  it('LAMMPS: enabled field → derived getForces()-style payload; disabled → null', () => {
    mountIds(idTags('lammps'))
    const api = initForcesCard({ engine: 'lammps', gizmo: makeGizmo(), getAnchorCount: () => 0 })
    drive(FORCES_FIELD_IDS.lammps, { mag: 4.2, dir: [0, 90] })
    const s = api.getFieldSpec()
    expect(s).toEqual({ field_pN: 4.2, dir: [0, 1, 0], enabled: true })
    clearDom()
    mountIds(idTags('lammps'))
    const api2 = initForcesCard({ engine: 'lammps', gizmo: makeGizmo() })
    drive(FORCES_FIELD_IDS.lammps, { enable: false, mag: 4.2 })
    const s2 = api2.getFieldSpec()
    expect((s2.enabled && s2.field_pN > 0) ? 'on' : null).toBeNull()
  })

  it('oxDNA ring drag changes direction without changing magnitude', () => {
    mountIds(idTags('oxdna'))
    const g = makeGizmo()
    const api = initForcesCard({ engine: 'oxdna', gizmo: g })
    document.getElementById(FORCES_FIELD_IDS.oxdna.toggle).click()   // open → attach → active
    drive(FORCES_FIELD_IDS.oxdna, { mag: 2 })
    g._fireDrag([1, 0, 0])
    const s = specOf(api)
    expect(s.field_pN).toBe(2)
    expect(s.dir).toEqual([1, 0, 0])
    expect(s.enabled).toBe(true)
  })

  it('angle spinners step by 5° and arrow offsets step by 2 nm without entering the field payload', () => {
    mountIds(idTags('oxdna'))
    const g = makeGizmo()
    const api = initForcesCard({ engine: 'oxdna', gizmo: g })
    const bag = FORCES_FIELD_IDS.oxdna
    expect(document.getElementById(bag.dirX).step).toBe('5')
    expect(document.getElementById(bag.dirY).step).toBe('5')
    const offset = document.getElementById('efield-offset-x')
    expect(offset.step).toBe('2')
    setInput(offset, 6)
    drive(bag, { mag: 3, dir: [90, 0] })
    expect(specOf(api)).toEqual({ field_pN: 3, dir: [0, 0, 1], enabled: true })
  })

  it('rotation-control visibility toggle defaults on and hides only the controls', () => {
    mountIds(idTags('oxdna'))
    const g = makeGizmo()
    initForcesCard({ engine: 'oxdna', gizmo: g })
    const toggle = document.querySelector('.efield-controls-toggle input')
    expect(toggle.checked).toBe(true)
    toggle.checked = false
    toggle.dispatchEvent(new Event('change', { bubbles: true }))
    expect(g.setControlsVisible).toHaveBeenLastCalledWith(false)
  })

  it('arrow stays world-origin based and its display offset never enters the payload', () => {
    mountIds(idTags('oxdna'))
    const g = makeGizmo()
    const api = initForcesCard({ engine: 'oxdna', gizmo: g })
    setInput(document.getElementById('efield-offset-x'), 6)
    expect(g.setOffset).toHaveBeenLastCalledWith([6, 0, 0])
    expect(api.getFieldSpec()).not.toHaveProperty('offset')
  })

  it('applyConfig repopulates magnitude + direction and enables the field', () => {
    mountIds(idTags('cando'))
    const api = initForcesCard({ engine: 'cando' })
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] }, { open: true })
    expect(document.getElementById(FORCES_FIELD_IDS.cando.enable).checked).toBe(true)
    expect(specOf(api)).toEqual({ field_pN: 5, dir: [1, 0, 0], enabled: true })
    api.applyConfig(null)
    expect(api.isEnabled()).toBe(false)
    expect(api.getFieldSpec().enabled).toBe(false)
  })
})

describe('initForcesCard — durable behavioural pins', () => {
  afterEach(() => clearDom())

  it('missing DOM → inert no-op with the engine default dir', () => {
    clearDom()
    const inert = initForcesCard({ engine: 'lammps' })
    expect(inert.getFieldSpec()).toEqual({ field_pN: 0, dir: [1, 0, 0], enabled: false })
    expect(inert.isEnabled()).toBe(false)
  })

  it('per-engine default direction: oxDNA/CanDo/NAMD +y, LAMMPS +x', () => {
    for (const [engine, want] of [['oxdna', [0, 1, 0]], ['cando', [0, 1, 0]], ['namd', [0, 1, 0]], ['lammps', [1, 0, 0]]]) {
      mountIds(idTags(engine))
      const api = initForcesCard({ engine, gizmo: makeGizmo() })
      expect(api.getFieldSpec().dir).toEqual(want)
      clearDom()
    }
  })

  it('enable + magnitude gate isEnabled', () => {
    mountIds(idTags('oxdna'))
    const api = initForcesCard({ engine: 'oxdna', gizmo: makeGizmo() })
    expect(api.isEnabled()).toBe(false)
    drive(FORCES_FIELD_IDS.oxdna, { mag: null })                     // enabled, no magnitude
    expect(api.getFieldSpec().enabled).toBe(true)
    expect(api.isEnabled()).toBe(false)
    setInput(document.getElementById(FORCES_FIELD_IDS.oxdna.mag), 2)
    expect(api.isEnabled()).toBe(true)
  })

  it('V/m helper computes force-per-nucleotide (present for oxDNA/CanDo/NAMD)', () => {
    const bag = FORCES_FIELD_IDS.cando
    mountIds(idTags('cando'))
    const api = initForcesCard({ engine: 'cando' })
    document.getElementById(bag.toggle).click()
    document.getElementById(bag.qeff).value = '0.25'
    document.getElementById(bag.vpm).value = '1000000'               // 1e6 V/m
    document.getElementById(bag.vpmApply).click()
    expect(api.getFieldSpec().field_pN).toBeCloseTo(0.0400544, 5)
  })

  it('the V/m sub-panel toggles none <-> grid (oxDNA/CanDo/NAMD)', () => {
    const bag = FORCES_FIELD_IDS.namd
    mountIds(idTags('namd'))
    initForcesCard({ engine: 'namd' })
    const vpm = document.getElementById(bag.vpmBody)
    vpm.style.display = 'none'
    document.getElementById(bag.vpmToggle).click()
    expect(vpm.style.display).toBe('grid')
    document.getElementById(bag.vpmToggle).click()
    expect(vpm.style.display).toBe('none')
  })

  it('LAMMPS ready line: weak-warn + contextual anchor note from getAnchorCount', () => {
    const bag = FORCES_FIELD_IDS.lammps
    mountIds(idTags('lammps'))
    let anchors = 0
    const api = initForcesCard({ engine: 'lammps', gizmo: makeGizmo(), getAnchorCount: () => anchors })
    document.getElementById(bag.toggle).click()
    drive(bag, { mag: 0.1 })                                         // below EFIELD_PN_LOW
    expect(document.getElementById(bag.ready).textContent).toMatch(/very weak/i)
    expect(document.getElementById(bag.ready).textContent).toMatch(/add ≥1 anchor/i)
    anchors = 1
    api.refresh()
    expect(document.getElementById(bag.ready).textContent).not.toMatch(/add ≥1 anchor/i)
  })

  it('leaving the Dynamics tab detaches the gizmo — never re-attaches (oxDNA + LAMMPS)', () => {
    // Regression: LAMMPS (closeOnLeaveTab:false, gate open-and-enabled) must detach on
    // leave even while the card is open+enabled — the old bespoke card detached
    // unconditionally; an earlier `_syncGizmo()` in the handler re-attached it.
    for (const engine of ['oxdna', 'lammps']) {
      mountIds(idTags(engine))
      const g = makeGizmo()
      initForcesCard({ engine, gizmo: g, getAnchorCount: () => 1 })
      document.getElementById(FORCES_FIELD_IDS[engine].toggle).click()   // open → attach
      drive(FORCES_FIELD_IDS[engine], { mag: 2 })                        // enable
      expect(g.isActive()).toBe(true)
      window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', { detail: { activeTab: 'view' } }))
      expect(g.detach).toHaveBeenCalled()
      expect(g.isActive()).toBe(false)
      clearDom()
    }
  })

  it('apply-style ready line: warns (non-blocking) on no anchor; verb "run" (oxDNA) vs "solve" (CanDo)', () => {
    const oxBag = FORCES_FIELD_IDS.oxdna
    mountIds(idTags('oxdna'))
    let anchors = 0
    const api = initForcesCard({ engine: 'oxdna', gizmo: makeGizmo(), getAnchorCount: () => anchors })
    document.getElementById(oxBag.toggle).click()
    expect(document.getElementById(oxBag.ready).textContent).toMatch(/add a field to the run/i)
    drive(oxBag, { mag: 2 })
    // No anchor → a WARNING notice (not a block): the structure will drift.
    expect(document.getElementById(oxBag.ready).textContent).toMatch(/no anchor/i)
    expect(document.getElementById(oxBag.ready).textContent).toMatch(/drift/i)
    // Add an anchor → the no-anchor warning clears.
    anchors = 1
    api.refresh()
    expect(document.getElementById(oxBag.ready).textContent).not.toMatch(/no anchor/i)
    clearDom()
    const cdBag = FORCES_FIELD_IDS.cando
    mountIds(idTags('cando'))
    initForcesCard({ engine: 'cando' })
    document.getElementById(cdBag.toggle).click()
    expect(document.getElementById(cdBag.ready).textContent).toMatch(/add a field to the solve/i)
  })
})
