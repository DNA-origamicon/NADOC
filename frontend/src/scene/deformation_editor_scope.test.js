import { afterEach, expect, it } from 'vitest'
import { store } from '../state/store.js'
import { cancelDeformation, exitTool, getDeformDefaultClusterIds, setDeformSessionClusterIds } from './deformation_editor.js'

afterEach(() => exitTool())

it('keeps the picked cluster through popup opening and plane reselection without an active selection marker', async () => {
  store.setState({ activeClusterId: null, currentDesign: { cluster_transforms: [{ id: 'a' }, { id: 'b' }] } })
  await setDeformSessionClusterIds(['b'])
  expect(getDeformDefaultClusterIds()).toEqual(['b'])
  cancelDeformation()
  expect(getDeformDefaultClusterIds()).toEqual(['b'])
  exitTool()
  expect(getDeformDefaultClusterIds()).toEqual([])
})
