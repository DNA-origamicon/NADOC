import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const IDS = {
  'oxdna-anchors-toggle': 'div', 'oxdna-anchors-arrow': 'span', 'oxdna-anchors-body': 'div',
  'oxdna-anchors-add': 'button', 'oxdna-anchors-clear': 'button',
  'oxdna-anchors-list': 'div', 'oxdna-anchors-status': 'div',
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
})
