import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const IDS = {
  'oxdna-anchors-toggle': 'div', 'oxdna-anchors-arrow': 'span', 'oxdna-anchors-body': 'div',
  'oxdna-anchors-add': 'button', 'oxdna-anchors-clear': 'button',
  'oxdna-anchors-list': 'div', 'oxdna-anchors-status': 'div', 'oxdna-anchors-glow': 'input',
}

const overhangSelection = (ids = []) => ({
  selection: { items: ids.map(id => ({ kind: 'overhang', id })) },
})

describe('initOxdnaAnchorsSetup', () => {
  let els, store, api

  beforeEach(() => {
    els = mountIds(IDS)
    store = createMockStore(overhangSelection())
    api = initOxdnaAnchorsSetup({ getSelection: () => store.getState() })
  })
  afterEach(() => clearDom())

  it('starts collapsed; the header toggles the body', () => {
    expect(els['oxdna-anchors-body'].style.display).toBe('none')
    els['oxdna-anchors-toggle'].click()
    expect(els['oxdna-anchors-body'].style.display).toBe('')
  })

  it('Add reads the current selection into the anchor set', () => {
    store.setState(overhangSelection(['o1', 'o2']))
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
    store.setState(overhangSelection(['o1', 'o2']))
    api.addSelectedAnchors()
    const x = els['oxdna-anchors-list'].querySelector('[data-key="overhang:o1"] span:last-child')
    x.click()
    expect(api.getAnchors().map(a => a.id)).toEqual(['o2'])
  })

  it('Clear removes all anchors', () => {
    store.setState(overhangSelection(['o1']))
    api.addSelectedAnchors()
    els['oxdna-anchors-clear'].click()
    expect(api.getAnchors()).toHaveLength(0)
  })

  it('the Add button click path also works (not just the api method)', () => {
    store.setState(overhangSelection(['oX']))
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
    const cstore = createMockStore(overhangSelection(['cq']))
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
      store.setState(overhangSelection(['o1']))
      a.addSelectedAnchors()
      expect(onChange).toHaveBeenCalledTimes(1)      // the Add did fire it

      els['oxdna-anchors-glow'].checked = false
      els['oxdna-anchors-glow'].dispatchEvent(new Event('change'))
      expect(onChange, 'looking at anchors must not recompose the run').toHaveBeenCalledTimes(1)
    })

    it('the anchor set survives toggling the halo off', () => {
      store.setState(overhangSelection(['o1']))
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
      store.setState(overhangSelection(['o1', 'o2', 'o3']))
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
      store.setState(overhangSelection(['o1']))
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
      const cstore = createMockStore(overhangSelection(['cq']))
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
      store.setState(overhangSelection(['o1', 'o2']))
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

// ── The Hold-atoms column (NAMD only, opt-in via ids.atoms) ──────────────────

const MD_IDS = {
  'md-anchors-toggle': 'div', 'md-anchors-arrow': 'span', 'md-anchors-body': 'div',
  'md-anchors-add': 'button', 'md-anchors-clear': 'button',
  'md-anchors-list': 'div', 'md-anchors-status': 'div', 'md-anchors-glow': 'input',
}
// The four presets exactly as index.html declares them — the card clones these.
const ATOM_OPTIONS = [
  ['', 'All heavy atoms (~20/base)'],
  ["C1'", 'C1′ only (1/base)'],
  ['P', 'P only (1/base)'],
  ["P,C1'", 'P + C1′ (2/base)'],
]

function mountAtomsSelect() {
  const sel = document.createElement('select')
  sel.id = 'md-anchors-atoms'
  for (const [value, label] of ATOM_OPTIONS) {
    const o = document.createElement('option')
    o.value = value; o.textContent = label
    sel.appendChild(o)
  }
  document.body.appendChild(sel)
  return sel
}

describe('the Hold-atoms column', () => {
  let els, store, api, atomsEl, onChange

  const rowSelect = (key) =>
    els['md-anchors-list'].querySelector(`[data-key="${key}"] select`)

  beforeEach(() => {
    els = mountIds(MD_IDS)
    atomsEl = mountAtomsSelect()
    store = createMockStore(overhangSelection())
    onChange = vi.fn()
    api = initOxdnaAnchorsSetup({
      getSelection: () => store.getState(),
      onChange,
      engine: 'namd',
      ids: {
        toggle: 'md-anchors-toggle', arrow: 'md-anchors-arrow', body: 'md-anchors-body',
        add: 'md-anchors-add', clear: 'md-anchors-clear', list: 'md-anchors-list',
        status: 'md-anchors-status', glow: 'md-anchors-glow', atoms: 'md-anchors-atoms',
      },
    })
    store.setState(overhangSelection(['o1', 'o2']))
    api.addSelectedAnchors()
  })
  afterEach(() => clearDom())

  it('gives every row a select cloned from the ONE preset list', () => {
    // The presets must not be duplicated into JS — a second copy would drift.
    const sel = rowSelect('overhang:o1')
    expect([...sel.options].map(o => [o.value, o.textContent])).toEqual(ATOM_OPTIONS)
  })

  it('renders NO column when the card was not given ids.atoms', () => {
    // The other six instances of this factory are non-NAMD and must be untouched.
    clearDom()
    const plain = mountIds({
      'oxdna-anchors-toggle': 'div', 'oxdna-anchors-arrow': 'span', 'oxdna-anchors-body': 'div',
      'oxdna-anchors-add': 'button', 'oxdna-anchors-clear': 'button',
      'oxdna-anchors-list': 'div', 'oxdna-anchors-status': 'div', 'oxdna-anchors-glow': 'input',
    })
    const s = createMockStore(overhangSelection(['o1']))
    initOxdnaAnchorsSetup({ getSelection: () => s.getState() }).addSelectedAnchors()
    expect(plain['oxdna-anchors-list'].querySelector('select')).toBeNull()
    expect(s.getState()).toBeTruthy()
  })

  it('a row select writes ONLY that row', () => {
    const sel = rowSelect('overhang:o1')
    sel.value = "C1'"
    sel.dispatchEvent(new Event('change'))
    const [a1, a2] = api.getAnchors()
    expect(a1.atoms).toEqual(["C1'"])
    expect(a2.atoms).toBeNull()          // still the all-heavy default it was added with
  })

  it('a row change fires onChange — the held atoms are part of the run, unlike focus', () => {
    onChange.mockClear()
    const sel = rowSelect('overhang:o2')
    sel.value = 'P'
    sel.dispatchEvent(new Event('change'))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].find(a => a.id === 'o2').atoms).toEqual(['P'])
  })

  it('a row change does not destroy the select it came from', () => {
    // A full re-render inside the select's own change handler would replace the element
    // mid-event. The row path must resync the group select only.
    const sel = rowSelect('overhang:o1')
    sel.value = 'P'
    sel.dispatchEvent(new Event('change'))
    expect(rowSelect('overhang:o1')).toBe(sel)
  })

  it('clicking a row select opens the dropdown instead of focusing the row', () => {
    rowSelect('overhang:o1').click()
    expect(api.getFocusKey()).toBeNull()
  })

  it('"Apply hold to all" writes every row', () => {
    atomsEl.value = "P,C1'"
    atomsEl.dispatchEvent(new Event('change'))
    expect(api.getAnchors().map(a => a.atoms)).toEqual([['P', "C1'"], ['P', "C1'"]])
    expect(rowSelect('overhang:o2').value).toBe("P,C1'")
  })

  it('goes BLANK when the rows disagree, and back to a value when they agree', () => {
    const sel = rowSelect('overhang:o1')
    sel.value = 'P'
    sel.dispatchEvent(new Event('change'))
    expect(atomsEl.selectedIndex).toBe(-1)

    const other = rowSelect('overhang:o2')
    other.value = 'P'
    other.dispatchEvent(new Event('change'))
    expect(atomsEl.value).toBe('P')
  })

  it('removing the odd row out un-blanks the group select', () => {
    const sel = rowSelect('overhang:o1')
    sel.value = 'P'
    sel.dispatchEvent(new Event('change'))
    expect(atomsEl.selectedIndex).toBe(-1)
    els['md-anchors-list'].querySelector('[data-key="overhang:o1"] [data-role="remove"]').click()
    expect(atomsEl.value).toBe('')
  })

  it('newly added anchors inherit whatever the group select shows', () => {
    atomsEl.value = "C1'"
    atomsEl.dispatchEvent(new Event('change'))
    store.setState(overhangSelection(['o1', 'o2', 'o3']))
    api.addSelectedAnchors()
    expect(api.getAnchors().find(a => a.id === 'o3').atoms).toEqual(["C1'"])
    expect(atomsEl.value).toBe("C1'")     // still uniform
  })

  it('re-adding an existing anchor preserves the atoms already on its row', () => {
    const sel = rowSelect('overhang:o1')
    sel.value = 'P'
    sel.dispatchEvent(new Event('change'))
    api.addSelectedAnchors()              // same selection, added again
    expect(api.getAnchors().find(a => a.id === 'o1').atoms).toEqual(['P'])
  })

  it('applyConfig restores a per-row choice from a job', () => {
    api.applyConfig([
      { kind: 'overhang', id: 'oA', atoms: ["C1'"] },
      { kind: 'overhang', id: 'oB', atoms: ['P'] },
    ])
    expect(rowSelect('overhang:oA').value).toBe("C1'")
    expect(rowSelect('overhang:oB').value).toBe('P')
    expect(atomsEl.selectedIndex).toBe(-1)   // mixed
  })

  it('applyConfig seeds rows with no atoms from the job-level default', () => {
    // A job prepared before per-anchor holds existed recorded the choice only once, as
    // manifest anchors.atom_names. Without this, selecting it would read as all-heavy.
    api.applyConfig([{ kind: 'overhang', id: 'oA' }, { kind: 'overhang', id: 'oB' }],
                    { defaultAtoms: ["C1'"] })
    expect(api.getAnchors().map(a => a.atoms)).toEqual([["C1'"], ["C1'"]])
    expect(atomsEl.value).toBe("C1'")
  })

  it('applyConfig does not overwrite an explicit all-heavy choice with the default', () => {
    // `atoms: null` is an anchor that deliberately holds everything; only key presence
    // separates it from "no opinion".
    api.applyConfig([{ kind: 'overhang', id: 'oA', atoms: null }], { defaultAtoms: ['P'] })
    expect(api.getAnchors()[0].atoms).toBeNull()
    expect(atomsEl.value).toBe('')
  })

  it('leaves a row blank for an atom set no preset offers', () => {
    api.applyConfig([{ kind: 'overhang', id: 'oA', atoms: ["O3'"] }])
    expect(rowSelect('overhang:oA').selectedIndex).toBe(-1)
    expect(api.getAnchors()[0].atoms).toEqual(["O3'"])   // and does not discard it
  })

  it('carries the per-row atoms into the halo event', () => {
    const seen = []
    const onEvt = (e) => seen.push(e.detail)
    window.addEventListener('nadoc:anchors-change', onEvt)
    try {
      const sel = rowSelect('overhang:o1')
      sel.value = 'P'
      sel.dispatchEvent(new Event('change'))
    } finally {
      window.removeEventListener('nadoc:anchors-change', onEvt)
    }
    expect(seen.at(-1).highlighted.find(a => a.id === 'o1').atoms).toEqual(['P'])
  })
})
