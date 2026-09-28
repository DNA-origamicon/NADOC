import * as THREE from 'three'
import { createVRUI } from './vr_ui.js'
import { validateVRAvatar } from './vr_avatar_protocol.js'

const vec = a => new THREE.Vector3().fromArray(a)
/** Analytic two-link IK, with an outward/downward elbow hint. Joints are estimates. */
export function estimateVRBody(head, hands) {
  const position = vec(head.position), orientation = new THREE.Quaternion().fromArray(head.orientation)
  const forward = new THREE.Vector3(0,0,-1).applyQuaternion(orientation); forward.y = 0
  if (forward.lengthSq() < 1e-6) forward.set(0,0,-1)
  forward.normalize()
  const right = forward.clone().cross(new THREE.Vector3(0,1,0))
  const neck = position.clone().addScaledVector(forward,-.08).add(new THREE.Vector3(0,-.22,0))
  const arms = hands.map((hand,i) => {
    const sign = i ? 1 : -1, shoulder = neck.clone().addScaledVector(right,sign*.18)
    if (!hand) return { shoulder: shoulder.toArray(), elbow: null }
    const wrist = vec(hand.position), axis = wrist.clone().sub(shoulder), d = axis.length()
    if (d > 1e-6) axis.divideScalar(d); else axis.copy(forward)
    // Preserve the measured wrist even outside the nominal reach envelope. This is
    // a stick figure, not a calibrated body: stretch both links equally if needed.
    const length = Math.max(.32,d*.5001), along = d*.5
    const hint = right.clone().multiplyScalar(sign*.65).add(new THREE.Vector3(0,-1,0)).addScaledVector(forward,-.2)
    hint.addScaledVector(axis,-hint.dot(axis))
    if (hint.lengthSq()<1e-6) { hint.copy(forward).addScaledVector(axis,-forward.dot(axis)) }
    if (hint.lengthSq()<1e-6) { hint.copy(right).addScaledVector(axis,-right.dot(axis)) }
    hint.normalize()
    const elbow = shoulder.clone().addScaledVector(axis,along).addScaledVector(hint,Math.sqrt(Math.max(0,length*length-along*along)))
    return { shoulder: shoulder.toArray(), elbow: elbow.toArray(), wrist: wrist.toArray() }
  })
  return { neck: neck.toArray(), arms }
}

/** Transient guest-only avatar; attached outside the scientific scene/package. */
export function createVRAvatar({ scene, now = () => performance.now() }) {
  const root = new THREE.Group(); root.name = 'vr-presenter-avatar'; root.matrixAutoUpdate = false; root.visible = false
  const cyan = new THREE.MeshBasicMaterial({color:0x42dce8}), orange = new THREE.MeshBasicMaterial({color:0xffb34d})
  const visor = new THREE.MeshBasicMaterial({color:0x19364b})
  const geometries = [], materials = [cyan,orange,visor]
  function box(size, material, parent=root) {
    const g = new THREE.BoxGeometry(...size); geometries.push(g)
    const m = new THREE.Mesh(g,material);parent.add(m);return m
  }
  const headset = new THREE.Group();root.add(headset)
  box([.21,.115,.14],cyan,headset).position.z=-.025
  box([.18,.075,.015],visor,headset).position.z=-.102
  const controllers = [0,1].map(i => {
    const group = new THREE.Group();root.add(group);box([.045,.11,.055],i?orange:cyan,group)
    box([.009,.009,.18],i?orange:cyan,group).position.z=-.11
    return group
  })
  function bone(material) {
    const g = new THREE.CylinderGeometry(.012,.012,1,8);geometries.push(g)
    const m = new THREE.Mesh(g,material);root.add(m);return m
  }
  const bones=[bone(cyan),bone(cyan),bone(cyan),bone(cyan),bone(orange),bone(orange)]
  const up = new THREE.Vector3(0,1,0)
  function segment(mesh,a,b) {
    const start=vec(a),end=vec(b),delta=end.clone().sub(start),length=delta.length()
    mesh.position.copy(start).add(end).multiplyScalar(.5);mesh.scale.set(1,Math.max(length,1e-6),1)
    if(length>1e-6)mesh.quaternion.setFromUnitVectors(up,delta.divideScalar(length))
  }
  const ui=createVRUI(root)
  scene?.add(root)
  let latest=null, expires=0, last=now()
  function receive(value) {
    try {
      latest = validateVRAvatar(value?.avatar?.pose ?? null)
      expires = now()+Math.max(0,Math.min(1500,(value?.avatar?.expiresAt ?? 0)-(value?.serverTime ?? 0)))
      if (!latest) root.visible=false
    } catch { latest=null;root.visible=false }
  }
  function frame() {
    const time=now(),alpha=1-Math.exp(-Math.min(.2,(time-last)/1000)*25);last=time
    if(!latest || time>=expires){root.visible=false;return}
    if(scene && root.parent!==scene)scene.add(root)
    ui.update(latest.ui)
    const first=!root.visible;root.visible=true;root.matrix.fromArray(latest.trackingToSource);root.matrixWorldNeedsUpdate=true
    function apply(group,p) {
      const fresh=first || !group.visible
      group.visible=!!p;if(!p)return
      const q=new THREE.Quaternion().fromArray(p.orientation)
      if(fresh){group.position.fromArray(p.position);group.quaternion.copy(q)}
      else {group.position.lerp(vec(p.position),alpha);group.quaternion.slerp(q,alpha)}
    }
    apply(headset,latest.head);controllers.forEach((g,i)=>apply(g,latest.hands[i]))
    const pose=g=>({position:g.position.toArray(),orientation:g.quaternion.toArray()})
    const body=estimateVRBody(pose(headset),controllers.map(g=>g.visible?pose(g):null))
    segment(bones[0],body.arms[0].shoulder,body.arms[1].shoulder)
    segment(bones[1],body.neck,headset.position.toArray())
    body.arms.forEach((arm,i)=>{
      bones[2+i*2].visible=bones[3+i*2].visible=!!arm.elbow
      if(arm.elbow){segment(bones[2+i*2],arm.shoulder,arm.elbow);segment(bones[3+i*2],arm.elbow,arm.wrist)}
    })
  }
  return { root, receive, frame, clear(){latest=null;root.visible=false}, dispose(){ui.dispose();root.removeFromParent();geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose())} }
}
