import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  bendAngleDeg,
  bendRadiusNm,
  closePopup,
  hasPolymerizationStrands,
  initBendTwistPopup,
  openPopup,
  polymerBendSpanBp,
} from './bend_twist_popup.js'
import { BDNA_RISE_PER_BP } from '../constants.js'
import { store } from '../state/store.js'

describe('bend radius/angle conversion', () => {
  it('calculates radius from the selected contour length and bend angle', () => {
    const span = 100
    expect(bendRadiusNm(90, span)).toBeCloseTo(span * BDNA_RISE_PER_BP / (Math.PI / 2), 10)
  })

  it('calculates bend angle when radius drives the bend', () => {
    expect(bendAngleDeg(20, 100)).toBeCloseTo(
      100 * BDNA_RISE_PER_BP / 20 * 180 / Math.PI,
      10,
    )
  })

  it('round-trips nonzero values and treats a straight bend as infinite radius', () => {
    const radius = bendRadiusNm(137.5, 63)
    expect(bendAngleDeg(radius, 63)).toBeCloseTo(137.5, 10)
    expect(bendRadiusNm(0, 63)).toBe(Infinity)
  })

  it('rejects a non-positive radius as a zero-angle bend', () => {
    expect(bendAngleDeg(0, 100)).toBe(0)
    expect(bendAngleDeg(-5, 100)).toBe(0)
  })

  it('recognizes only routed designs with connector strands and a periodic seam', () => {
    const routed = {
      strands: [{ notes: 'polymerization connector' }],
      forced_ligations: [{ is_periodic_seam: true }],
    }
    expect(hasPolymerizationStrands(routed)).toBe(true)
    expect(hasPolymerizationStrands({ ...routed, forced_ligations: [] })).toBe(false)
    expect(hasPolymerizationStrands({ ...routed, strands: [] })).toBe(false)
  })

  it('measures the actually bent part of staggered polymer seams', () => {
    const design = {
      forced_ligations: [
        { is_periodic_seam: true, three_prime_bp: -9, five_prime_bp: 326 },
        { is_periodic_seam: true, three_prime_bp: 330, five_prime_bp: -5 },
        { is_periodic_seam: true, three_prime_bp: -2, five_prime_bp: 333 },
      ],
    }
    // Bend window [-5, 333]: overlaps are 331, 335 and 335 bp.
    expect(polymerBendSpanBp(design, -5, 333)).toBeCloseTo(1001 / 3, 10)
  })
})

describe('bend radius field', () => {
  afterEach(() => {
    closePopup()
    store.setState({ currentDesign: null })
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('synchronizes angle to radius in both directions and previews the driven angle', () => {
    document.body.innerHTML = `
      <div id="deform-panel"><span id="def-panel-title"></span>
        <div id="def-twist-controls"></div><div id="def-bend-controls"></div>
        <input id="def-twist-value"><span id="def-twist-value-label"></span><span id="def-twist-unit"></span>
        <input type="radio" id="def-twist-rh"><input type="radio" id="def-twist-lh">
        <input type="radio" id="def-twist-total-radio"><input type="radio" id="def-twist-pernm-radio">
        <input id="def-bend-dir"><input id="def-bend-angle"><input id="def-bend-radius">
        <label id="def-polymer-circle-label"><input type="checkbox" id="def-polymer-circle"></label>
        <div id="def-polymer-count-row"><input id="def-polymer-count" value="3"></div>
        <svg id="def-compass"><line id="def-compass-arm"></line><circle id="def-compass-handle"></circle></svg>
        <input type="checkbox" id="def-preview-check"><button id="def-cancel-btn"></button><button id="def-apply-btn"></button>
        <input id="def-plane-a-bp"><input id="def-plane-b-bp"><span id="def-plane-a-nm"></span><span id="def-plane-b-nm"></span>
        <div id="def-cluster-section"><div id="def-cluster-list"></div><div id="def-cluster-empty-msg"></div></div>
        <button id="def-cluster-all-btn"></button><button id="def-cluster-none-btn"></button>
        <div id="def-bend-hint"></div><div id="def-feasibility"></div>
      </div>`
    const onPreview = vi.fn()
    initBendTwistPopup({ onPreview, onConfirm: vi.fn(), onCancel: vi.fn() })
    openPopup('bend', 0, 100, null, [])

    const angle = document.getElementById('def-bend-angle')
    const radius = document.getElementById('def-bend-radius')
    angle.value = '90'
    angle.dispatchEvent(new Event('input'))
    expect(Number(radius.value)).toBeCloseTo(100 * BDNA_RISE_PER_BP / (Math.PI / 2), 4)

    radius.value = '20'
    radius.dispatchEvent(new Event('input'))
    const expectedAngle = 100 * BDNA_RISE_PER_BP / 20 * 180 / Math.PI
    expect(Number(angle.value)).toBeCloseTo(expectedAngle, 3)
    expect(onPreview.mock.lastCall[0].curvature_deg_per_bp).toBeCloseTo(expectedAngle / 100, 5)
  })

  it('enables circle mode only for a routed part and makes the copy count drive the bend', () => {
    store.setState({
      currentDesign: {
        strands: [{ notes: 'polymerization connector' }],
        forced_ligations: [{
          is_periodic_seam: true, three_prime_bp: 0, five_prime_bp: 90,
        }],
      },
    })
    document.body.innerHTML = `
      <div id="deform-panel"><span id="def-panel-title"></span>
        <div id="def-twist-controls"></div><div id="def-bend-controls"></div>
        <input id="def-twist-value"><span id="def-twist-value-label"></span><span id="def-twist-unit"></span>
        <input type="radio" id="def-twist-rh"><input type="radio" id="def-twist-lh">
        <input type="radio" id="def-twist-total-radio"><input type="radio" id="def-twist-pernm-radio">
        <input id="def-bend-dir"><input id="def-bend-angle"><input id="def-bend-radius">
        <label id="def-polymer-circle-label"><input type="checkbox" id="def-polymer-circle"></label>
        <div id="def-polymer-count-row"><input id="def-polymer-count" value="3"></div>
        <svg id="def-compass"><line id="def-compass-arm"></line><circle id="def-compass-handle"></circle></svg>
        <input type="checkbox" id="def-preview-check"><button id="def-cancel-btn"></button><button id="def-apply-btn"></button>
        <input id="def-plane-a-bp"><input id="def-plane-b-bp"><span id="def-plane-a-nm"></span><span id="def-plane-b-nm"></span>
        <div id="def-cluster-section"><div id="def-cluster-list"></div><div id="def-cluster-empty-msg"></div></div>
        <button id="def-cluster-all-btn"></button><button id="def-cluster-none-btn"></button>
        <div id="def-bend-hint"></div><div id="def-feasibility"></div>
      </div>`
    const onPreview = vi.fn()
    initBendTwistPopup({ onPreview, onConfirm: vi.fn(), onCancel: vi.fn() })
    openPopup('bend', 0, 100, null, [])

    const toggle = document.getElementById('def-polymer-circle')
    toggle.checked = true
    toggle.dispatchEvent(new Event('change'))

    const angle = document.getElementById('def-bend-angle')
    const radius = document.getElementById('def-bend-radius')
    expect(toggle.disabled).toBe(false)
    // The typed bend window is 100 bp, but the polymer seam sees 90 bp of it.
    // The stored curvature therefore makes the seam rotate 120°, while the
    // angle displayed between the typed planes is 133.333…°.
    const expectedAngle = (120 / 90) * 100
    expect(Number(angle.value)).toBeCloseTo(expectedAngle, 5)
    expect(angle.readOnly).toBe(true)
    expect(Number(radius.value)).toBeCloseTo(bendRadiusNm(expectedAngle, 100), 4)
    expect(onPreview.mock.lastCall[0].curvature_deg_per_bp).toBeCloseTo(120 / 90, 7)
    expect(onPreview.mock.lastCall[0].polymer_circle_count).toBe(3)
  })


  it('restores persisted circle mode and count from bend parameters', () => {
    store.setState({
      currentDesign: {
        strands: [{ notes: 'polymerization connector' }],
        forced_ligations: [{
          is_periodic_seam: true, three_prime_bp: 0, five_prime_bp: 100,
        }],
      },
    })
    document.body.innerHTML = `
      <div id="deform-panel"><span id="def-panel-title"></span>
        <div id="def-twist-controls"></div><div id="def-bend-controls"></div>
        <input id="def-twist-value"><span id="def-twist-value-label"></span><span id="def-twist-unit"></span>
        <input type="radio" id="def-twist-rh"><input type="radio" id="def-twist-lh">
        <input type="radio" id="def-twist-total-radio"><input type="radio" id="def-twist-pernm-radio">
        <input id="def-bend-dir"><input id="def-bend-angle"><input id="def-bend-radius">
        <label id="def-polymer-circle-label"><input type="checkbox" id="def-polymer-circle"></label>
        <div id="def-polymer-count-row"><input id="def-polymer-count" value="3"></div>
        <svg id="def-compass"><line id="def-compass-arm"></line><circle id="def-compass-handle"></circle></svg>
        <input type="checkbox" id="def-preview-check"><button id="def-cancel-btn"></button><button id="def-apply-btn"></button>
        <input id="def-plane-a-bp"><input id="def-plane-b-bp"><span id="def-plane-a-nm"></span><span id="def-plane-b-nm"></span>
        <div id="def-cluster-section"><div id="def-cluster-list"></div><div id="def-cluster-empty-msg"></div></div>
        <button id="def-cluster-all-btn"></button><button id="def-cluster-none-btn"></button>
        <div id="def-bend-hint"></div><div id="def-feasibility"></div>
      </div>`
    initBendTwistPopup({ onPreview: vi.fn(), onConfirm: vi.fn(), onCancel: vi.fn() })
    openPopup('bend', 0, 100, {
      kind: 'bend', curvature_deg_per_bp: 0.6, direction_deg: 0,
      polymer_circle_count: 5,
    }, [], true)

    expect(document.getElementById('def-polymer-circle').checked).toBe(true)
    expect(document.getElementById('def-polymer-count').value).toBe('5')
    expect(document.getElementById('def-polymer-count-row').style.display).toBe('')
    expect(document.getElementById('def-bend-angle').readOnly).toBe(true)
  })
})
