import { Vector3 } from 'three'
import { axisSegments } from '../scene/multiscale_nav.js'
import { navigationDesign } from '../scene/reference_navigation.js'
import { computeGroupHiddenInstanceIds } from '../scene/assembly_groups_util.js'

/** Navigation must refer to the visible assembly placements, not the last edited part. */
export function preparedNavigation(state, assemblyRenderer) {
  if (!state.assemblyActive) return axisSegments(navigationDesign(state))
  const hidden = computeGroupHiddenInstanceIds(state.currentAssembly), result = [], point = new Vector3()
  for (const instance of state.currentAssembly?.instances ?? []) {
    if (instance.visible === false || hidden.has(instance.id)) continue
    const design = assemblyRenderer?.getInstanceDesign?.(instance.id)
    const matrix = assemblyRenderer?.getInstanceBackboneEntries?.(instance.id)?.matrixWorld
    if (!matrix) continue
    const axes = axisSegments(navigationDesign({ ...state, currentDesign: design }))
    for (let i = 0; i < axes.length; i += 3) {
      point.fromArray(axes, i).applyMatrix4(matrix)
      result.push(point.x, point.y, point.z)
    }
  }
  return new Float64Array(result)
}
