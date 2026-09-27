import { it, expect } from 'vitest'
import { Matrix4 } from 'three'
import { preparedNavigation } from './prepared_navigation.js'
it('exports visible instance axes in world coordinates and excludes inactive part axes', () => {
  const design = { helices: [{ axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 5 } }] }
  const state = { assemblyActive: true, currentDesign: design, currentAssembly: {
    instances: [{ id: 'a' }, { id: 'b', visible: false }, { id: 'c' }],
    groups: [{ id: 'hidden', visible: false, instance_ids: ['c'] }],
  } }
  const renderer = { getInstanceDesign: () => design, getInstanceBackboneEntries: () => ({ matrixWorld: new Matrix4().makeTranslation(30, 2, 0) }) }
  expect([...preparedNavigation(state, renderer)]).toEqual([30,2,0,30,2,5])
  expect([...preparedNavigation({ ...state, assemblyActive: false }, renderer)]).toEqual([0,0,0,0,0,5])
  expect(preparedNavigation(state, null).length).toBe(0)
})
