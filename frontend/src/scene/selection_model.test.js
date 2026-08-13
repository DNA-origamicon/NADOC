import { describe, expect, it } from 'vitest'
import {
  createSelectionState, resetSelectionForReload, reduceSelection,
  reconcileSelection, selectedRefsOfKind, primarySelectionRef, canonicalSelection,
  selectedStrandIds, relatedStrandIds, selectedOverhangIds, selectedExtensionIds,
  selectedClusterIds, primaryOverhangId, primaryExtensionId, primaryClusterId,
  selectedCrossoverRefs, primaryCrossoverRef, selectedEndRefs, primaryEndRef,
  overhangSelectionTarget, extensionSelectionTarget,
} from './selection_model.js'

const strand = id => ({ kind: 'strand', id })
const overhang = id => ({ kind: 'overhang', id })
const base = key => ({ kind: 'base', key })

describe('selection_model — approved Phase 1 reducer contract', () => {
  it('creates a normalized empty design selection', () => {
    expect(createSelectionState()).toEqual({ context: 'design', level: 'default', items: [], primary: null })
  })

  it('normalizes items, removes duplicates, and keeps primary inside the set', () => {
    const state = createSelectionState({
      context: 'bad', level: 'bad', items: [strand('a'), strand('a'), overhang('o')],
      primary: strand('missing'),
    })
    expect(state.context).toBe('design')
    expect(state.level).toBe('default')
    expect(state.items).toEqual([strand('a'), overhang('o')])
    expect(state.primary).toEqual(overhang('o'))
  })

  it('replace is unconditional while select applies sole-item re-click clearing', () => {
    let state = reduceSelection(undefined, { type: 'replace', ref: strand('a') })
    expect(state.items).toEqual([strand('a')])
    state = reduceSelection(state, { type: 'replace', ref: strand('a') })
    expect(state.items).toEqual([strand('a')])
    state = reduceSelection(state, { type: 'select', ref: strand('a') })
    expect(state.items).toEqual([])
  })

  it('select replaces a different selection and makes it primary', () => {
    const start = createSelectionState({ items: [strand('a'), strand('b')] })
    const state = reduceSelection(start, { type: 'select', ref: overhang('o') })
    expect(state.items).toEqual([overhang('o')])
    expect(state.primary).toEqual(overhang('o'))
  })

  it('toggle is its own inverse for membership', () => {
    const start = createSelectionState({ items: [strand('a')] })
    const added = reduceSelection(start, { type: 'toggle', ref: strand('b') })
    expect(added.items).toEqual([strand('a'), strand('b')])
    expect(added.primary).toEqual(strand('b'))
    const removed = reduceSelection(added, { type: 'toggle', ref: strand('b') })
    expect(removed.items).toEqual([strand('a')])
    expect(removed.primary).toEqual(strand('a'))
  })

  it('extend preserves existing order and promotes explicitly selected refs to most recent', () => {
    const start = createSelectionState({ items: [strand('a'), strand('b')] })
    const state = reduceSelection(start, { type: 'extend', refs: [strand('a'), strand('c')] })
    expect(state.items).toEqual([strand('b'), strand('a'), strand('c')])
    expect(state.primary).toEqual(strand('c'))
  })

  it('clear keeps context and level', () => {
    const start = createSelectionState({ context: 'assembly', level: 'base', items: [base('h:1:FORWARD')] })
    expect(reduceSelection(start, { type: 'clear' })).toEqual({
      context: 'assembly', level: 'base', items: [], primary: null,
    })
  })

  it('setLevel changes policy without changing selected identity', () => {
    const start = createSelectionState({ items: [strand('a')] })
    expect(reduceSelection(start, { type: 'setLevel', level: 'domain' })).toEqual({
      ...start, level: 'domain',
    })
  })

  it.each(['reload', 'changeContext'])('%s clears selection and resets level to default', (type) => {
    const start = createSelectionState({ context: 'design', level: 'base', items: [strand('a')] })
    expect(reduceSelection(start, { type, context: 'assembly' })).toEqual({
      context: 'assembly', level: 'default', items: [], primary: null,
    })
  })

  it('resetSelectionForReload never preserves level, including same-context reload', () => {
    expect(resetSelectionForReload('design').level).toBe('default')
    expect(resetSelectionForReload('assembly').level).toBe('default')
  })

  it('reconciliation preserves order and primary when live', () => {
    const start = createSelectionState({ items: [strand('a'), strand('b'), strand('c')], primary: strand('b') })
    const state = reconcileSelection(start, ref => ref.id !== 'a')
    expect(state.items).toEqual([strand('b'), strand('c')])
    expect(state.primary).toEqual(strand('b'))
  })

  it('reconciliation falls back to the most recent survivor when primary is removed', () => {
    const start = createSelectionState({ items: [strand('a'), strand('b'), strand('c')], primary: strand('c') })
    const state = reconcileSelection(start, ref => ref.id !== 'c')
    expect(state.items).toEqual([strand('a'), strand('b')])
    expect(state.primary).toEqual(strand('b'))
    expect(reconcileSelection(state, () => true)).toEqual(state)
  })

  it('selectors return normalized typed refs without leaking internal arrays', () => {
    const state = createSelectionState({ items: [strand('a'), overhang('o')] })
    expect(selectedRefsOfKind(state, 'strand')).toEqual([strand('a')])
    expect(primarySelectionRef(state)).toEqual(overhang('o'))
  })

  it('selects direct strand ownership from either a slice or full store state', () => {
    const selection = createSelectionState({ items: [
      strand('s1'), { kind: 'domain', strandId: 's2', domainIndex: 0 },
      { kind: 'domain', strandId: 's1', domainIndex: 1 }, overhang('o1'),
    ] })
    expect(canonicalSelection({ selection })).toEqual(selection)
    expect(selectedStrandIds({ selection })).toEqual(['s1', 's2'])
  })

  it('overhang selection is one overhang ref, never a compound domain item', () => {
    const state = reduceSelection(undefined, { type: 'select', ref: overhang('oh1') })
    expect(state.items).toEqual([{ kind: 'overhang', id: 'oh1' }])
    expect(selectedRefsOfKind(state, 'domain')).toEqual([])
  })

  it('keeps ordered cluster identity and the most-recent cluster primary', () => {
    const state = createSelectionState({ items: [
      { kind: 'cluster', id: 'c1' }, { kind: 'cluster', id: 'c2' },
    ] })
    expect(selectedClusterIds(state)).toEqual(['c1', 'c2'])
    expect(primaryClusterId(state)).toBe('c2')
  })

  it('keeps crossover subtype in ordered identity and primary selection', () => {
    const state = createSelectionState({ items: [
      { kind: 'crossover', id: 'x1', subtype: 'crossover' },
      { kind: 'crossover', id: 'f1', subtype: 'forced_ligation' },
    ] })
    expect(selectedCrossoverRefs(state)).toEqual(state.items)
    expect(primaryCrossoverRef(state)).toEqual(state.items[1])
  })

  it('keeps End refs distinct from Base refs at the same nucleotide key', () => {
    const end = { kind: 'end', key: 'h1:3:FORWARD' }
    const state = createSelectionState({ items: [base(end.key), end] })
    expect(state.items).toHaveLength(2)
    expect(selectedEndRefs(state)).toEqual([end])
    expect(primaryEndRef(state)).toEqual(end)
  })

  it('derives overhang and extension identities plus their live parent strands', () => {
    const selection = createSelectionState({ items: [
      overhang('oh1'), { kind: 'extension', id: 'ext1' }, overhang('oh2'),
    ] })
    const state = {
      selection,
      currentDesign: {
        overhangs: [{ id: 'oh1', strand_id: 's1' }, { id: 'oh2', strand_id: 's2' }],
        extensions: [{ id: 'ext1', strand_id: 's1', end: 'five_prime' }],
        strands: [
          { id: 's1', domains: [{ overhang_id: 'oh1' }] },
          { id: 's2', domains: [{ overhang_id: 'oh2' }] },
        ],
      },
    }
    expect(selectedOverhangIds(state)).toEqual(['oh1', 'oh2'])
    expect(selectedExtensionIds(state)).toEqual(['ext1'])
    expect(primaryOverhangId(state)).toBe('oh2')
    expect(primaryExtensionId(state)).toBeNull()
    expect(selectedStrandIds(state)).toEqual([])
    expect(relatedStrandIds(state)).toEqual(['s1', 's2'])
    expect(overhangSelectionTarget(state)).toMatchObject({
      overhang: { id: 'oh2', strand_id: 's2' }, strandId: 's2', domainIndex: 0,
    })
    expect(extensionSelectionTarget(state, { kind: 'extension', id: 'ext1' })).toMatchObject({
      extension: { id: 'ext1', strand_id: 's1', end: 'five_prime' }, strandId: 's1',
    })
  })

  it('ignores malformed intents without mutating the logical state', () => {
    const start = createSelectionState({ items: [strand('a')] })
    expect(reduceSelection(start, { type: 'select', ref: { kind: 'base', key: 'bad' } })).toEqual(start)
    expect(reduceSelection(start, { type: 'wat' })).toEqual(start)
  })
})
