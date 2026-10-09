import * as THREE from 'three'
import { sampleLiveSweep, bindSweepCloud, moveSweepCloud, sweepFrameQuaternion, SWEEP_LIVE_BUDGET } from './sweep_live_path.js'

/** Fixed-size GPU buffers: point/rotation input never rebuilds tubes or topology. */
export function createSweepLivePreview(parent) {
  const group = new THREE.Group(); group.name='sweep-live-preview'; group.visible=false; parent.add(group)
  const pathBuffer = new THREE.Float32BufferAttribute(new Float32Array(512*3),3).setUsage(THREE.DynamicDrawUsage)
  const cloudBuffer = new THREE.Float32BufferAttribute(new Float32Array(SWEEP_LIVE_BUDGET*3),3).setUsage(THREE.DynamicDrawUsage)
  const path = new THREE.Line(new THREE.BufferGeometry().setAttribute('position',pathBuffer),
    new THREE.LineBasicMaterial({color:new THREE.Color().setRGB(.3,1,.4),depthTest:false}))
  const cloud = new THREE.Points(new THREE.BufferGeometry().setAttribute('position',cloudBuffer),
    new THREE.PointsMaterial({color:new THREE.Color().setRGB(.12,.65,.45),size:3,sizeAttenuation:false}))
  path.name='sweep-live-path'; cloud.name='sweep-live-cloud'; path.frustumCulled=cloud.frustumCulled=false
  group.add(path,cloud)
  let data=null, basis, initial, bindings=[]
  return {
    group,
    reset(){data=null;bindings=[];group.visible=false},
    setBaseline(response,draft={}) {
      data=response;group.visible=false
      basis=sweepFrameQuaternion(data.orientation_basis ?? [[1,0,0],[0,1,0],[0,0,1]])
      initial=draft.source_helix_id && data.point_bases?.[0]
        ? new THREE.Vector3(...data.point_bases[0].map(row=>row[2])) : null
      const baseline=sampleLiveSweep(data.points_nm,draft.orientations_deg,basis,initial)
      bindings=baseline?bindSweepCloud(data,baseline):[]
    },
    update(values,angles) {
      if(!data)return null
      const rotation=new THREE.Matrix3().set(...(data.point_rotation ?? [[1,0,0],[0,1,0],[0,0,1]]).flat())
      const origin=new THREE.Vector3(...(data.origin_nm ?? data.points_nm[0]))
      const points=values.map(p=>new THREE.Vector3(...p).applyMatrix3(rotation).add(origin).toArray())
      const sampled=sampleLiveSweep(points,angles,basis,initial)
      if(!sampled){group.visible=false;return null}
      sampled.positions.forEach((p,i)=>p.toArray(pathBuffer.array,3*i))
      path.geometry.setDrawRange(0,sampled.positions.length);pathBuffer.needsUpdate=true
      moveSweepCloud(bindings,sampled,cloudBuffer.array)
      cloud.geometry.setDrawRange(0,bindings.length);cloudBuffer.needsUpdate=true
      group.visible=true
      return sampled
    },
    dispose(){group.removeFromParent();path.geometry.dispose();path.material.dispose();cloud.geometry.dispose();cloud.material.dispose()},
  }
}
