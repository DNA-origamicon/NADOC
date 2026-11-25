import { photoBackboneRadius } from './backbone_spheres.js'
import { AdditiveBlending } from 'three'
import { reprOf } from './mesh_repr.js'

export function materialAvailability(scene) {
  const representations = new Set()
  let unsupported = 0
  scene.traverseVisible(obj => {
    if (!obj.isMesh || !obj.material || obj.userData?.photoFloor || obj.material.visible === false) return
    if (obj.isInstancedMesh && obj.count === 0) return
    const src = obj.material
    if (src.blending === AdditiveBlending) return
    if (Array.isArray(src) || ((src.userData?.isImpostor || src.userData?.impostorRadius != null) && photoBackboneRadius(obj) == null) ||
        obj.userData?.photoMaterialKind === 'gold-nanoparticle' ||
        (obj.userData?.sharedLodImpostor && obj.name !== 'assemblySurface' && !obj.userData?.applySharedInstancing)) {
      unsupported++; return
    }
    representations.add(reprOf(obj))
  })
  return { representations: [...representations], unsupported }
}
