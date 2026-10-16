import { expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { armToolClusterSelection, beginClusterSelection } from './tool_cluster_selection.js'

function setup(state = {}) {
  const store = createMockStore({ currentDesign: { id: 'design' }, ...state })
  const controller = createSelectionController({ store })
  const finish = armToolClusterSelection({ store, selectionManager: { setSelectionLevel: controller.setLevel } })
  return { store, controller, finish }
}

it('arms cluster picking, then resets to default without losing the gesture selection', async () => {
  const { store, controller } = setup({ selectableTypes: { overhangs: true, scaffold: false } })
  expect(controller.getState().level).toBe('cluster')
  expect(store.getState().selectableTypes).toMatchObject({ overhangs: false, scaffold: true, staples: true })
  controller.clear()
  await Promise.resolve()
  expect(controller.getState().level).toBe('cluster')
  controller.select({ kind: 'cluster', id: 'first' })
  controller.extend([{ kind: 'cluster', id: 'second' }])
  await Promise.resolve()
  expect(controller.getState().level).toBe('default')
  expect(controller.getState().items).toHaveLength(2)
  controller.setLevel('domain')
  controller.select({ kind: 'strand', id: 'manual' })
  await Promise.resolve()
  expect(controller.getState().level).toBe('domain')
})

it('allows cycling to another level while waiting and resets after that pick', async () => {
  const { controller } = setup()
  controller.setLevel('strand')
  await Promise.resolve()
  expect(controller.getState().level).toBe('strand')
  controller.select({ kind: 'strand', id: 's' })
  await Promise.resolve()
  expect(controller.getState().level).toBe('default')
})

it('does not replace an existing tool target or assembly selection policy', () => {
  const selection = { level: 'domain', items: [{ kind: 'strand', id: 's' }] }
  const selected = setup({ selection })
  expect(selected.controller.getState()).toMatchObject(selection)
  const assembly = setup({ assemblyActive: true, selection: { level: 'strand', items: [] } })
  expect(assembly.controller.getState().level).toBe('strand')
})

it('cancels pending reset callbacks and returns to default on close or document change', async () => {
  const { store, controller, finish } = setup()
  controller.select({ kind: 'cluster', id: 'c' })
  finish()
  expect(controller.getState().level).toBe('default')
  controller.setLevel('base')
  await Promise.resolve()
  expect(controller.getState().level).toBe('base')
  const next = setup()
  next.store.setState({ currentDesign: { id: 'other' } })
  await Promise.resolve()
  expect(next.controller.getState().level).toBe('default')
})

it.each(['selected', 'cancelled'])('uses explicit placement picking and restores the prior mode when %s', async outcome => {
  const placement = { id: 'placement' }
  const store = createMockStore({ currentDesign: {
    id: 'design', group_organization: { version: 1, groups: [] }, cluster_transforms: [placement],
  }, selectableTypes: { overhangs: true } })
  const controller = createSelectionController({ store })
  let pickMode = 'groups'
  const onSelected = vi.fn()
  const picker = beginClusterSelection({ store, onSelected, selectionManager: {
    setSelectionLevel: controller.setLevel, clearSelection: controller.clear,
    getGroupPickMode: () => pickMode, setGroupPickMode: value => { pickMode = value },
  } })
  expect(pickMode).toBe('placements')
  if (outcome === 'selected') controller.select({ kind: 'cluster', id: placement.id })
  else picker.cancel()
  await Promise.resolve()
  expect(pickMode).toBe('groups')
  expect(controller.getState().level).toBe('default')
  expect(store.getState().selectableTypes).toEqual({ overhangs: true })
  if (outcome === 'selected') expect(onSelected).toHaveBeenCalledWith(placement)
  else expect(onSelected).not.toHaveBeenCalled()
})
