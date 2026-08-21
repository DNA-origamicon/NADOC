// @vitest-environment jsdom
/**
 * Tests for the oxDNA surface capture-strand setup card.
 *
 * The card is a submit-time SOURCE (getStrandsSpec feeds the job payload) and an
 * echo-back SINK (applyConfig repaints it from a selected job's run_config), and the
 * two disagreed: selecting a run that carried capture strands left the enable checkbox
 * disabled — because the hard-surface prerequisite gate is only pushed by the floor
 * card's onChange, which its own applyConfig never fires — so the card read as "off"
 * for a job that genuinely had them.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initOxdnaSurfaceStrandsSetup } from './oxdna_surface_strands_setup.js'

const IDS = {
  'oxdna-surfstrand-enable': 'input', 'oxdna-surfstrand-controls': 'div',
  'oxdna-surfstrand-seq': 'input', 'oxdna-surfstrand-gen': 'button',
  'oxdna-surfstrand-end': 'select', 'oxdna-surfstrand-density': 'input',
  'oxdna-surfstrand-shape': 'select', 'oxdna-surfstrand-size': 'input',
  'oxdna-surfstrand-size-label': 'span', 'oxdna-surfstrand-offx': 'input',
  'oxdna-surfstrand-offy': 'input', 'oxdna-surfstrand-seed': 'input',
  'oxdna-surfstrand-seed-new': 'button', 'oxdna-surfstrand-field': 'input',
  'oxdna-surfstrand-status': 'div', 'oxdna-surfstrand-highlight': 'input',
  'oxdna-surfstrand-showshape': 'input', 'oxdna-surfstrand-color': 'input',
  'oxdna-surfstrand-color-hex': 'input',
}

function mount() {
  const els = mountIds(IDS)
  for (const id of ['enable', 'field', 'highlight', 'showshape']) {
    els[`oxdna-surfstrand-${id}`].type = 'checkbox'
  }
  els['oxdna-surfstrand-field'].checked = true
  for (const [id, opts] of [['end', ["5'", "3'"]], ['shape', ['circle', 'square']]]) {
    for (const v of opts) {
      const o = document.createElement('option'); o.value = v
      els[`oxdna-surfstrand-${id}`].appendChild(o)
    }
  }
  els['oxdna-surfstrand-size'].value = '100'
  els['oxdna-surfstrand-density'].value = '0'
  els['oxdna-surfstrand-seed'].value = '1'
  return els
}

const SPEC = {
  enabled: true, sequence: 'TTTTGCTAGC', attachEnd: "5'", shape: 'circle',
  sizeNm: 100, densityPerUm2: 3000, offsetXNm: 0, offsetYNm: 0, seed: 7,
  subjectToField: false,
}

describe('initOxdnaSurfaceStrandsSetup', () => {
  beforeEach(() => { vi.useFakeTimers(); mount() })
  afterEach(() => { vi.useRealTimers(); clearDom() })

  it('is gated on the hard surface: no surface → cannot be enabled', () => {
    const card = initOxdnaSurfaceStrandsSetup({})
    const chk = document.getElementById('oxdna-surfstrand-enable')
    expect(chk.disabled).toBe(true)
    chk.checked = true
    chk.dispatchEvent(new Event('change'))
    expect(chk.checked).toBe(false)      // the gate refuses it
    expect(card.isEnabled()).toBe(false)
    expect(card.getStrandsSpec()).toBeNull()
  })

  it('produces the submit spec once the surface is on', () => {
    const card = initOxdnaSurfaceStrandsSetup({})
    card.setSurfaceEnabled(true)
    const chk = document.getElementById('oxdna-surfstrand-enable')
    expect(chk.disabled).toBe(false)
    chk.checked = true
    chk.dispatchEvent(new Event('change'))
    document.getElementById('oxdna-surfstrand-seq').value = 'TTTTGCTAGC'
    document.getElementById('oxdna-surfstrand-density').value = '3000'
    expect(card.getStrandsSpec()).toMatchObject({
      enabled: true, sequence: 'TTTTGCTAGC', densityPerUm2: 3000, sizeNm: 100, count: 24,
    })
  })

  // The regression: a run that carried capture strands came back with the toggle off.
  it('echo-back keeps the toggle ON for a job that has capture strands', () => {
    const card = initOxdnaSurfaceStrandsSetup({})
    card.setSurfaceEnabled(true)     // main re-syncs the gate before applyConfig
    card.applyConfig(SPEC)
    const chk = document.getElementById('oxdna-surfstrand-enable')
    expect(chk.checked).toBe(true)
    expect(chk.disabled).toBe(false)
    expect(card.isEnabled()).toBe(true)
    expect(card.getStrandsSpec()).toMatchObject({
      enabled: true, sequence: 'TTTTGCTAGC', densityPerUm2: 3000, subjectToField: false,
    })
  })

  it('echo-back turns it off for a job that has none', () => {
    const card = initOxdnaSurfaceStrandsSetup({})
    card.setSurfaceEnabled(true)
    card.applyConfig(SPEC)
    card.applyConfig(null)
    expect(document.getElementById('oxdna-surfstrand-enable').checked).toBe(false)
    expect(card.getStrandsSpec()).toBeNull()
  })

  // Order matters: applying the spec first and syncing the gate afterwards drops it,
  // because setSurfaceEnabled(false) force-clears an enabled card.
  it('losing the hard surface clears the strands with it', () => {
    const card = initOxdnaSurfaceStrandsSetup({})
    card.setSurfaceEnabled(true)
    card.applyConfig(SPEC)
    card.setSurfaceEnabled(false)
    expect(card.isEnabled()).toBe(false)
    expect(document.getElementById('oxdna-surfstrand-enable').checked).toBe(false)
    expect(document.getElementById('oxdna-surfstrand-enable').disabled).toBe(true)
  })

  it('coalesces typed edits into one onChange but repaints the count immediately', () => {
    const onChange = vi.fn()
    const card = initOxdnaSurfaceStrandsSetup({ onChange })
    card.setSurfaceEnabled(true)
    card.applyConfig(SPEC)
    onChange.mockClear()
    const dens = document.getElementById('oxdna-surfstrand-density')
    for (const v of ['1', '10', '100', '1000']) {
      dens.value = v
      dens.dispatchEvent(new Event('input'))
    }
    expect(onChange).not.toHaveBeenCalled()          // still inside the debounce
    expect(document.getElementById('oxdna-surfstrand-status').textContent).toContain('8 strands')
    vi.advanceTimersByTime(200)
    expect(onChange).toHaveBeenCalledTimes(1)        // one rebuild, not four
  })

  it('a throwing onChange cannot freeze the card', () => {
    const onChange = vi.fn(() => { throw new Error('renderer blew up') })
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const card = initOxdnaSurfaceStrandsSetup({ onChange })
    card.setSurfaceEnabled(true)
    card.applyConfig(SPEC)
    const size = document.getElementById('oxdna-surfstrand-size')
    size.value = '200'
    size.dispatchEvent(new Event('input'))
    vi.advanceTimersByTime(200)
    expect(card.getStrandsSpec().sizeNm).toBe(200)   // the card still tracks its fields
    expect(document.getElementById('oxdna-surfstrand-status').textContent).toContain('94 strands')
  })
})
