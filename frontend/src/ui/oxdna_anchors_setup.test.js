import { describe, it, expect, beforeEach, afterEach } from 'vitest'
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
})
