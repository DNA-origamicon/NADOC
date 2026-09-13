import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects, CONE_RADIUS } from './helix_renderer.js'

function fixture() {
  const positions = [[0,0,0],[.5,0,.1],[.6,.5,.2],[.1,.6,.3],[0,.1,.4]]
  const design = {
    helices: [{ id:'g4',bp_start:0,length_bp:5,axis_start:{x:0,y:0,z:0},axis_end:{x:0,y:0,z:2},native_residues:[{}] }],
    strands:[{id:'apt',strand_type:'staple',color:'#A855F7',sequence:'GGTTG',domains:[{helix_id:'g4',start_bp:0,end_bp:4,direction:'FORWARD'}]}],
    crossovers:[],overhangs:[],cluster_transforms:[],
  }
  const geometry = positions.map((p,i) => ({helix_id:'g4',bp_index:i,direction:'FORWARD',strand_id:'apt',strand_type:'staple',domain_index:0,
    is_five_prime:i===0,base:'GGTTG'[i],backbone_position:p,base_position:[p[0]+.2,p[1],p[2]],base_normal:[1,0,0],axis_tangent:[0,0,1]}))
  const axes = {g4:{start:positions[0],end:positions.at(-1),samples:positions}}
  return {design,geometry,axes}
}

describe('native aptamer Full representation', () => {
  it('uses strand-colored cones without a second axis tube across LOD switches', () => {
    const {design,geometry,axes} = fixture()
    const ctrl = buildHelixObjects(geometry,design,new THREE.Scene(),{apt:0xA855F7},[],axes,'full')
    expect(ctrl.coneEntries).toHaveLength(4)
    const color = new THREE.Color()
    for (const cone of ctrl.coneEntries) {
      expect(cone.coneRadius).toBe(CONE_RADIUS)
      expect(cone.strandId).toBe('apt')
      cone.instMesh.getColorAt(cone.id,color)
      expect(color.getHexString()).toBe('a855f7')
    }
    for (const lod of [2,0,1,0]) {
      ctrl.setDetailLevel(lod)
      ctrl.setAxisArrowsVisible(true)
      ctrl.setAxisShaftMode('deformed')
      const axes = []
      ctrl.root.traverse(o => { if(o.name==='axisLine') axes.push(o) })
      expect(axes).toHaveLength(0)
      expect(ctrl.coneEntries[0].instMesh.visible).toBe(lod!==2)
    }
  })

  it('moves and rotates the live cone endpoints with the backbone', () => {
    const {design,geometry,axes} = fixture()
    const ctrl = buildHelixObjects(geometry,design,new THREE.Scene(),{apt:0xA855F7},[],axes,'full')
    const pivot = new THREE.Vector3(.2,.3,.4)
    const destination = pivot.clone().add(new THREE.Vector3(3,-2,1))
    const rotation = new THREE.Quaternion().setFromEuler(new THREE.Euler(.2,.5,.7))
    ctrl.captureClusterBase(['g4'])
    ctrl.applyClusterTransform(['g4'],pivot,destination,rotation)
    for (const cone of ctrl.coneEntries) {
      const a = new THREE.Vector3(...geometry[cone.fromNuc.bp_index].backbone_position)
      const b = new THREE.Vector3(...geometry[cone.toNuc.bp_index].backbone_position)
      const expected = a.add(b).multiplyScalar(.5).sub(pivot).applyQuaternion(rotation).add(destination)
      const matrix = new THREE.Matrix4()
      cone.instMesh.getMatrixAt(cone.id,matrix)
      expect(new THREE.Vector3().setFromMatrixPosition(matrix).distanceTo(expected)).toBeLessThan(1e-6)
    }
  })
})
