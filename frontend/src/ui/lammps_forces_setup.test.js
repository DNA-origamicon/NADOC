// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { initLammpsForcesSetup } from './lammps_forces_setup.js'

const $ = (id) => document.getElementById(id)

// Three separate collapsible cards, mirroring the oxDNA panel.
const MARKUP = `
  <div id="lammps-field-toggle"><span id="lammps-field-arrow"></span></div>
  <div id="lammps-field-body" style="display:none">
    <input id="lammps-field-enable" type="checkbox">
    <input id="lammps-field-mag" type="number" value="0">
    <input id="lammps-field-dir-x" type="number" value="1">
    <input id="lammps-field-dir-y" type="number" value="0">
    <input id="lammps-field-dir-z" type="number" value="0">
    <div id="lammps-field-ready"></div>
  </div>
  <div id="lammps-anchors-toggle"><span id="lammps-anchors-arrow"></span></div>
  <div id="lammps-anchors-body" style="display:none">
    <button id="lammps-anchors-add"></button>
    <button id="lammps-anchors-clear"></button>
    <div id="lammps-anchors-list"></div>
    <div id="lammps-anchors-status"></div>
  </div>
  <div id="lammps-surface-toggle"><span id="lammps-surface-arrow"></span></div>
  <div id="lammps-surface-body" style="display:none">
    <input id="lammps-surface-enable" type="checkbox">
    <div id="lammps-surface-controls" style="display:none">
      <select id="lammps-surface-axis"><option value="-y" selected>-y</option><option value="+z">+z</option></select>
      <input id="lammps-surface-offset" type="range" value="0">
      <span id="lammps-surface-offset-label"></span>
      <input id="lammps-surface-stiff" type="number" value="5">
    </div>
    <div id="lammps-surface-ready"></div>
  </div>`

function fakeGizmo() {
  let vec = [1, 0, 0], active = false
  return {
    attach: () => { active = true }, detach: () => { active = false },
    isActive: () => active, getVector: () => vec, setVector: (v) => { vec = v },
    setColor: vi.fn(), setOnChange: vi.fn(),
  }
}
const openCard = (id) => $(`lammps-${id}-toggle`).click()

beforeEach(() => { document.body.innerHTML = MARKUP })

describe('initLammpsForcesSetup — separate cards', () => {
  it('no-op when no card is present', () => {
    document.body.innerHTML = ''
    const s = initLammpsForcesSetup()
    expect(s.getForces()).toEqual({ field: null, anchors: [], wall: null })
  })

  it('field is null until enabled with a positive magnitude', () => {
    const s = initLammpsForcesSetup({ gizmo: fakeGizmo() })
    expect(s.getForces().field).toBe(null)
    $('lammps-field-enable').checked = true
    $('lammps-field-enable').dispatchEvent(new Event('change'))
    expect(s.getForces().field).toBe(null)            // still 0 pN
    $('lammps-field-mag').value = '25'
    $('lammps-field-mag').dispatchEvent(new Event('input'))
    expect(s.getForces().field).toEqual({ field_pN: 25, dir: [1, 0, 0] })
  })

  it('warns when the field is below the useful floor', () => {
    initLammpsForcesSetup({ gizmo: fakeGizmo() })
    $('lammps-field-enable').checked = true
    $('lammps-field-enable').dispatchEvent(new Event('change'))
    $('lammps-field-mag').value = '0.06'
    $('lammps-field-mag').dispatchEvent(new Event('input'))
    expect($('lammps-field-ready').textContent).toMatch(/very weak/i)
  })

  it('adds anchors from the scene selection and reports fieldNeedsAnchor', () => {
    const state = { selectedObject: { type: 'strand', id: 's1' } }
    const s = initLammpsForcesSetup({ gizmo: fakeGizmo(), getSelection: () => state })
    $('lammps-field-enable').checked = true
    $('lammps-field-enable').dispatchEvent(new Event('change'))
    $('lammps-field-mag').value = '25'; $('lammps-field-mag').dispatchEvent(new Event('input'))
    expect(s.fieldNeedsAnchor()).toBe(true)
    $('lammps-anchors-add').click()
    expect(s.getForces().anchors).toEqual([{ kind: 'strand', id: 's1' }])
    expect(s.fieldNeedsAnchor()).toBe(false)
    $('lammps-anchors-clear').click()
    expect(s.getForces().anchors).toEqual([])
    expect(s.fieldNeedsAnchor()).toBe(true)
  })

  it('gizmo attaches only when the FIELD card is open AND the field is enabled', () => {
    const gizmo = fakeGizmo()
    initLammpsForcesSetup({ gizmo })
    openCard('field')                                 // open the field card
    expect(gizmo.isActive()).toBe(false)              // open but field off
    $('lammps-field-enable').checked = true
    $('lammps-field-enable').dispatchEvent(new Event('change'))
    expect(gizmo.isActive()).toBe(true)
    openCard('field')                                 // collapse it again
    expect(gizmo.isActive()).toBe(false)
  })

  it('surface card produces a wall spec (axis-aligned) only when enabled', () => {
    const s = initLammpsForcesSetup({ gizmo: fakeGizmo() })
    expect(s.getForces().wall).toBe(null)
    $('lammps-surface-enable').checked = true
    $('lammps-surface-enable').dispatchEvent(new Event('change'))
    // default -y side (normal +y), stiff 5
    const wall = s.getForces().wall
    expect(wall.dir).toEqual([0, 1, 0])
    expect(wall.stiff).toBe(5)
    expect(wall).toHaveProperty('offset_nm')
    // controls become visible + a zero-stiffness disables it
    expect($('lammps-surface-controls').style.display).not.toBe('none')
    $('lammps-surface-stiff').value = '0'
    $('lammps-surface-stiff').dispatchEvent(new Event('input'))
    expect(s.getForces().wall).toBe(null)
  })

  it('the three cards collapse independently', () => {
    initLammpsForcesSetup({ gizmo: fakeGizmo() })
    openCard('surface')
    expect($('lammps-surface-body').style.display).toBe('')
    expect($('lammps-field-body').style.display).toBe('none')     // unaffected
    expect($('lammps-anchors-body').style.display).toBe('none')
  })

  it('exposes getAnchors and fires onChange on anchor changes (not during construction)', () => {
    const onChange = vi.fn()
    const state = { selectedObject: { type: 'strand', id: 's1' } }
    const s = initLammpsForcesSetup({ gizmo: fakeGizmo(), getSelection: () => state, onChange })
    expect(onChange).not.toHaveBeenCalled()          // silent during construction
    expect(s.getAnchors()).toEqual([])
    $('lammps-anchors-add').click()
    expect(s.getAnchors()).toEqual([{ kind: 'strand', id: 's1' }])
    expect(onChange).toHaveBeenCalled()              // anchor glow refresh fires
  })

  it('drives the surface grid on/off (never during construction)', () => {
    const setSurfaceGrid = vi.fn()
    initLammpsForcesSetup({ gizmo: fakeGizmo(), setSurfaceGrid })
    expect(setSurfaceGrid).not.toHaveBeenCalled()    // silent during construction
    $('lammps-surface-enable').checked = true
    $('lammps-surface-enable').dispatchEvent(new Event('change'))
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(
      expect.objectContaining({ enabled: true, axis: '-y' }))
    $('lammps-surface-enable').checked = false
    $('lammps-surface-enable').dispatchEvent(new Event('change'))
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(
      expect.objectContaining({ enabled: false }))
  })
})
