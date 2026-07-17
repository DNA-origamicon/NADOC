import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const IDS = {
  'oxdna-anchors-toggle': 'div', 'oxdna-anchors-arrow': 'span', 'oxdna-anchors-body': 'div',
  'oxdna-anchors-add': 'button', 'oxdna-anchors-clear': 'button',
  'oxdna-anchors-list': 'div', 'oxdna-anchors-status': 'div', 'oxdna-anchors-glow': 'input',
}

describe('initOxdnaAnchorsSetup', () => {
  let els, store, api

  beforeEach(() => {
    els = mountIds(IDS)
    store = createMockStore({ multiSelectedOverhangIds: [], multiSelectedDomainIds: [], selectedObject: null })
    api = initOxdnaAnchorsSetup({ getSelection: () => store.getState() })
  })
  afterEach(() => clearDom())

  it('starts collapsed; the header toggles the body', () => {
    expect(els['oxdna-anchors-body'].style.display).toBe('none')
    els['oxdna-anchors-toggle'].click()
    expect(els['oxdna-anchors-body'].style.display).toBe('')
  })

  it('Add reads the current selection into the anchor set', () => {
    store.setState({ multiSelectedOverhangIds: ['o1', 'o2'] })
    const added = api.addSelectedAnchors()
    expect(added).toBe(2)
    expect(api.getAnchors().map(a => a.id).sort()).toEqual(['o1', 'o2'])
  })

  it('Add with nothing selected warns and adds nothing', () => {
    const added = api.addSelectedAnchors()
    expect(added).toBe(0)
    expect(api.getAnchors()).toHaveLength(0)
    expect(els['oxdna-anchors-status'].textContent).toMatch(/select an overhang/i)
  })

  it('a chip remove ✕ drops that anchor', () => {
    store.setState({ multiSelectedOverhangIds: ['o1', 'o2'] })
    api.addSelectedAnchors()
    const x = els['oxdna-anchors-list'].querySelector('[data-key="overhang:o1"] span:last-child')
    x.click()
    expect(api.getAnchors().map(a => a.id)).toEqual(['o2'])
  })

  it('Clear removes all anchors', () => {
    store.setState({ multiSelectedOverhangIds: ['o1'] })
    api.addSelectedAnchors()
    els['oxdna-anchors-clear'].click()
    expect(api.getAnchors()).toHaveLength(0)
  })

  it('the Add button click path also works (not just the api method)', () => {
    store.setState({ multiSelectedOverhangIds: ['oX'] })
    els['oxdna-anchors-add'].click()
    expect(api.getAnchors().map(a => a.id)).toEqual(['oX'])
  })

  it('ids override drives a second (CanDo) skeleton, leaving the oxDNA one untouched', () => {
    // The CanDo FEM panel mounts its own cando-anchors-* card and instantiates a parallel
    // instance via the ids override; it must bind those ids, not the default oxDNA ones.
    const CANDO = {
      'cando-anchors-toggle': 'div', 'cando-anchors-arrow': 'span', 'cando-anchors-body': 'div',
      'cando-anchors-add': 'button', 'cando-anchors-clear': 'button',
      'cando-anchors-list': 'div', 'cando-anchors-status': 'div',
    }
    const cels = mountIds(CANDO)
    const cstore = createMockStore({ multiSelectedOverhangIds: ['cq'] })
    const capi = initOxdnaAnchorsSetup({
      getSelection: () => cstore.getState(),
      ids: {
        toggle: 'cando-anchors-toggle', arrow: 'cando-anchors-arrow', body: 'cando-anchors-body',
        add: 'cando-anchors-add', clear: 'cando-anchors-clear', list: 'cando-anchors-list',
        status: 'cando-anchors-status',
      },
    })
    cels['cando-anchors-add'].click()
    expect(capi.getAnchors().map(a => a.id)).toEqual(['cq'])       // bound the cando ids
    expect(cels['cando-anchors-list'].querySelector('[data-key="overhang:cq"]')).toBeTruthy()
    expect(api.getAnchors()).toHaveLength(0)                        // default oxDNA instance untouched
    expect(els['oxdna-anchors-list'].children.length).toBe(0)
  })

  it('applyConfig replaces the anchor set + notifies onChange (job-select echo)', () => {
    const onChange = vi.fn()
    const a = initOxdnaAnchorsSetup({ getSelection: () => store.getState(), onChange })
    a.applyConfig([
      { kind: 'overhang', id: 'o1' },
      { kind: 'domain', strandId: 's1', domainIndex: 2 },
    ])
    expect(a.getAnchors()).toHaveLength(2)
    expect(els['oxdna-anchors-list'].querySelector('[data-key="domain:s1:2"]')).toBeTruthy()
    expect(onChange).toHaveBeenLastCalledWith(a.getAnchors())
    // A second apply replaces (not appends); empty clears.
    a.applyConfig([{ kind: 'cluster', id: 'c9' }])
    expect(a.getAnchors().map(x => x.id)).toEqual(['c9'])
    a.applyConfig([])
    expect(a.getAnchors()).toHaveLength(0)
  })

  describe('Highlight anchors in 3D toggle', () => {
    it('defaults ON — and the default comes from the factory, not the markup', () => {
      // The fixture mounts a BARE <input> (checked=false, i.e. markup that forgot `checked`).
      // The card must still start on, and tick the box to match.
      expect(api.isGlowOn()).toBe(true)
      expect(els['oxdna-anchors-glow'].checked).toBe(true)
    })

    it('unticking it turns the halo off; re-ticking turns it back on', () => {
      const seen = []
      const listen = e => seen.push(e.detail.glow)
      window.addEventListener('nadoc:anchors-change', listen)
      try {
        els['oxdna-anchors-glow'].checked = false
        els['oxdna-anchors-glow'].dispatchEvent(new Event('change'))
        expect(api.isGlowOn()).toBe(false)
        expect(seen.at(-1)).toBe(false)

        els['oxdna-anchors-glow'].checked = true
        els['oxdna-anchors-glow'].dispatchEvent(new Event('change'))
        expect(api.isGlowOn()).toBe(true)
        expect(seen.at(-1)).toBe(true)
      } finally {
        window.removeEventListener('nadoc:anchors-change', listen)
      }
    })

    it('the toggle is display-only — it must NOT fire onChange (would recompose a live run)', () => {
      const onChange = vi.fn()
      const a = initOxdnaAnchorsSetup({ getSelection: () => store.getState(), onChange })
      store.setState({ multiSelectedOverhangIds: ['o1'] })
      a.addSelectedAnchors()
      expect(onChange).toHaveBeenCalledTimes(1)      // the Add did fire it

      els['oxdna-anchors-glow'].checked = false
      els['oxdna-anchors-glow'].dispatchEvent(new Event('change'))
      expect(onChange, 'looking at anchors must not recompose the run').toHaveBeenCalledTimes(1)
    })

    it('the anchor set survives toggling the halo off', () => {
      store.setState({ multiSelectedOverhangIds: ['o1'] })
      api.addSelectedAnchors()
      els['oxdna-anchors-glow'].checked = false
      els['oxdna-anchors-glow'].dispatchEvent(new Event('change'))
      expect(api.getAnchors().map(a => a.id)).toEqual(['o1'])
    })
  })

  describe('chip highlighting + click-to-focus', () => {
    const chip = (k) => els['oxdna-anchors-list'].querySelector(`[data-key="${k}"]`)
    const lit = () => [...els['oxdna-anchors-list'].querySelectorAll('[data-hl="1"]')].map(e => e.dataset.key)

    beforeEach(() => {
      store.setState({ multiSelectedOverhangIds: ['o1', 'o2', 'o3'] })
      api.addSelectedAnchors()
    })

    it('with the toggle on, every chip is purple and every anchor is lit in 3D', () => {
      expect(lit().sort()).toEqual(['overhang:o1', 'overhang:o2', 'overhang:o3'])
      expect(api.getHighlighted()).toHaveLength(3)
      // NB: the chip's PURPLE is not asserted here — jsdom's cssstyle drops this whole
      // cssText block (the border + border-radius combo; the pre-change string does it too),
      // so style.cssText reads '' regardless. Colour is verified in the app by screenshot;
      // data-hl is the semantic pin.
      expect(chip('overhang:o1').dataset.hl).toBe('1')
    })

    it('clicking one chip lights ONLY it — the rest un-highlight', () => {
      chip('overhang:o2').click()
      expect(api.getFocusKey()).toBe('overhang:o2')
      expect(lit()).toEqual(['overhang:o2'])
      expect(api.getHighlighted()).toEqual([{ kind: 'overhang', id: 'o2' }])
      expect(chip('overhang:o1').dataset.hl).toBeUndefined()
    })

    it('clicking the focused chip again re-highlights all — while the toggle is on', () => {
      chip('overhang:o2').click()
      chip('overhang:o2').click()
      expect(api.getFocusKey()).toBeNull()
      expect(lit().sort()).toEqual(['overhang:o1', 'overhang:o2', 'overhang:o3'])
    })

    it('clicking off the focused chip with the toggle OFF un-highlights everything', () => {
      els['oxdna-anchors-glow'].checked = false
      els['oxdna-anchors-glow'].dispatchEvent(new Event('change'))
      chip('overhang:o2').click()
      expect(lit(), 'focus beats the toggle — an explicit click still shows that one').toEqual(['overhang:o2'])
      chip('overhang:o2').click()
      expect(api.getFocusKey()).toBeNull()
      expect(lit(), 'toggle off + no focus → nothing lit').toEqual([])
      expect(api.getHighlighted()).toEqual([])
    })

    it('clicking the empty space beside the chips also drops focus', () => {
      chip('overhang:o2').click()
      expect(api.getFocusKey()).toBe('overhang:o2')
      els['oxdna-anchors-list'].click()          // e.target === the list container
      expect(api.getFocusKey()).toBeNull()
      expect(lit()).toHaveLength(3)
    })

    it('the × still removes (it must not focus the chip instead)', () => {
      chip('overhang:o1').querySelector('span:last-child').click()
      expect(api.getAnchors().map(a => a.id)).toEqual(['o2', 'o3'])
      expect(api.getFocusKey(), 'removing is not focusing').toBeNull()
    })

    it('removing the FOCUSED chip drops focus (no anchor left to point at)', () => {
      chip('overhang:o2').click()
      chip('overhang:o2').querySelector('span:last-child').click()
      expect(api.getFocusKey()).toBeNull()
      expect(lit().sort(), 'back to the toggle → the survivors light up').toEqual(['overhang:o1', 'overhang:o3'])
    })

    it('focusing is display-only — it must NOT fire onChange', () => {
      const onChange = vi.fn()
      const a = initOxdnaAnchorsSetup({ getSelection: () => store.getState(), onChange })
      a.addSelectedAnchors()
      onChange.mockClear()
      els['oxdna-anchors-list'].querySelector('[data-key="overhang:o2"]').click()
      expect(onChange, 'looking at one anchor must not recompose the run').not.toHaveBeenCalled()
    })

    it('the event carries the highlighted subset the halo should draw', () => {
      const seen = []
      const listen = e => seen.push(e.detail)
      window.addEventListener('nadoc:anchors-change', listen)
      try {
        chip('overhang:o2').click()
        expect(seen.at(-1).highlighted).toEqual([{ kind: 'overhang', id: 'o2' }])
        expect(seen.at(-1).focusKey).toBe('overhang:o2')
        expect(seen.at(-1).anchors, 'the full set still rides along').toHaveLength(3)
      } finally {
        window.removeEventListener('nadoc:anchors-change', listen)
      }
    })

    it('applyConfig (job-select echo) starts the new set unfocused', () => {
      chip('overhang:o2').click()
      api.applyConfig([{ kind: 'cluster', id: 'c9' }])
      expect(api.getFocusKey()).toBeNull()
      expect(lit()).toEqual(['cluster:c9'])
    })
  })

  describe('nadoc:anchors-change (drives the purple halo for every engine)', () => {
    let seen
    const listen = (e) => seen.push(e.detail)

    beforeEach(() => { seen = []; window.addEventListener('nadoc:anchors-change', listen) })
    afterEach(() => window.removeEventListener('nadoc:anchors-change', listen))

    it('fires on Add, tagged with the engine, carrying the new anchor set', () => {
      store.setState({ multiSelectedOverhangIds: ['o1'] })
      api.addSelectedAnchors()
      expect(seen).toHaveLength(1)
      expect(seen[0].engine).toBe('oxdna')                       // default tag
      expect(seen[0].anchors).toEqual([{ kind: 'overhang', id: 'o1' }])
      expect(seen[0].glow, 'halo state rides along so the listener needs no back-channel').toBe(true)
    })

    it('carries the engine tag its panel was built with', () => {
      const cels = mountIds({
        'cando-anchors-toggle': 'div', 'cando-anchors-arrow': 'span', 'cando-anchors-body': 'div',
        'cando-anchors-add': 'button', 'cando-anchors-clear': 'button',
        'cando-anchors-list': 'div', 'cando-anchors-status': 'div',
      })
      const cstore = createMockStore({ multiSelectedOverhangIds: ['cq'] })
      initOxdnaAnchorsSetup({
        engine: 'cando',
        getSelection: () => cstore.getState(),
        ids: {
          toggle: 'cando-anchors-toggle', arrow: 'cando-anchors-arrow', body: 'cando-anchors-body',
          add: 'cando-anchors-add', clear: 'cando-anchors-clear', list: 'cando-anchors-list',
          status: 'cando-anchors-status',
        },
      })
      cels['cando-anchors-add'].click()
      expect(seen.map(d => d.engine)).toEqual(['cando'])
    })

    it('fires on chip-remove, Clear and applyConfig too, so the halo tracks every edit', () => {
      store.setState({ multiSelectedOverhangIds: ['o1', 'o2'] })
      api.addSelectedAnchors()
      els['oxdna-anchors-list'].querySelector('[data-key="overhang:o1"] span:last-child').click()
      expect(seen.at(-1).anchors).toEqual([{ kind: 'overhang', id: 'o2' }])
      els['oxdna-anchors-clear'].click()
      expect(seen.at(-1).anchors).toEqual([])
      api.applyConfig([{ kind: 'cluster', id: 'c9' }])
      expect(seen.at(-1).anchors).toEqual([{ kind: 'cluster', id: 'c9' }])
    })

    it('does not fire during construction (nothing changed yet)', () => {
      initOxdnaAnchorsSetup({ getSelection: () => store.getState() })
      expect(seen).toHaveLength(0)
    })
  })
})
