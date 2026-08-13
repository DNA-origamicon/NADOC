import { describe, expect, it, vi } from 'vitest'
import { createSelectionState } from './selection_model.js'
import { createSelectionController } from './selection_controller.js'

function fakeStore(initial = {}) {
  let state = { selection: createSelectionState(), ...initial }
  return { getState: () => state, setState: vi.fn(update => { state = { ...state, ...update } }) }
}

describe('selection_controller — canonical sole writer', () => {
  it('commits only canonical selection in one atomic store update', () => {
    const store = fakeStore()
    const controller = createSelectionController({ store })
    controller.select({ kind: 'strand', id: 's1' })

    expect(store.setState).toHaveBeenCalledTimes(1)
    const update = store.setState.mock.calls[0][0]
    expect(Object.keys(update)).toEqual(['selection'])
    expect(update.selection).toEqual({
      context: 'design', level: 'default',
      items: [{ kind: 'strand', id: 's1' }],
      primary: { kind: 'strand', id: 's1' },
    })
  })

  it('exposes every reducer mutation as a canonical transaction', () => {
    const store = fakeStore()
    const controller = createSelectionController({ store })
    controller.replace([{ kind: 'strand', id: 's1' }])
    controller.extend([{ kind: 'strand', id: 's2' }])
    controller.toggle({ kind: 'strand', id: 's1' })
    controller.setLevel('base')
    controller.clear()

    expect(store.setState).toHaveBeenCalledTimes(5)
    expect(controller.getState()).toEqual({
      context: 'design', level: 'base', items: [], primary: null,
    })
  })

  it('reload clears items and resets level through one atomic commit', () => {
    const store = fakeStore({ selection: createSelectionState({
      level: 'base', items: [{ kind: 'strand', id: 's1' }],
    }) })
    const controller = createSelectionController({ store })

    expect(controller.reload('assembly')).toEqual({
      context: 'assembly', level: 'default', items: [], primary: null,
    })
    expect(store.setState).toHaveBeenCalledTimes(1)
  })

  it('keeps the design selection empty and inert while assembly owns interaction', () => {
    const store = fakeStore()
    const controller = createSelectionController({ store })
    controller.reload('assembly')
    store.setState.mockClear()

    controller.replace([{ kind: 'strand', id: 'hidden-design-strand' }])
    controller.setLevel('base')
    controller.reconcile(() => true)

    expect(store.setState).not.toHaveBeenCalled()
    expect(controller.getState()).toEqual({
      context: 'assembly', level: 'default', items: [], primary: null,
    })
    controller.reload('design')
    expect(controller.getState()).toEqual({
      context: 'design', level: 'default', items: [], primary: null,
    })
  })

  it('reconciles deleted refs without changing surviving order or primary', () => {
    const store = fakeStore({ selection: createSelectionState({ items: [
      { kind: 'strand', id: 's1' }, { kind: 'strand', id: 'gone' },
      { kind: 'strand', id: 's2' },
    ] }) })
    const controller = createSelectionController({ store })

    expect(controller.reconcile(ref => ref.id !== 'gone').items).toEqual([
      { kind: 'strand', id: 's1' }, { kind: 'strand', id: 's2' },
    ])
    expect(store.setState).toHaveBeenCalledTimes(1)
  })

  it('rejects a store without the required state interface', () => {
    expect(() => createSelectionController({ store: {} })).toThrow(/requires a store/)
  })
})
