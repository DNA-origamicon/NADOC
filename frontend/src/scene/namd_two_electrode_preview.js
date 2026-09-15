import * as THREE from 'three'

/** Schematic dimensions in nm only; never contributes atoms to exports or jobs. */
export function initTwoElectrodePreview({ scene, camera, controls }) {
  const group = new THREE.Group()
  group.name = 'NAMD two-electrode setup preview'
  group.userData.setupOnly = true
  group.visible = false
  scene.add(group)
  let lastDimensions = null
  function clear() {
    group.traverse(node => { node.geometry?.dispose(); node.material?.dispose() })
    group.clear()
    group.visible = false
  }
  function update({ detail } = {}) {
    clear()
    const s = detail?.spec
    if (!detail?.enabled || !s) { lastDimensions = null; return }
    const axis = {x:0,y:1,z:2}[s.normal]
    const lateral = [0,1,2].filter(i => i !== axis)
    const dims = [0,0,0]
    dims[axis] = s.gap_nm; dims[lateral[0]] = s.width_nm; dims[lateral[1]] = s.depth_nm
    if (axis == null || dims.some(v => !Number.isFinite(v) || v <= 0)) return
    const boxGeometry = new THREE.BoxGeometry(...dims)
    const box = new THREE.LineSegments(new THREE.EdgesGeometry(boxGeometry), new THREE.LineBasicMaterial({color:0x8b949e}))
    boxGeometry.dispose(); box.name = 'Electrolyte compartment outline'; group.add(box)
    const normal = new THREE.Vector3().setComponent(axis,1)
    const rotation = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,0,1),normal)
    // Local plane basis is arbitrary under rotation; construct its dimensions from world lateral axes instead.
    const basis = new THREE.Matrix4().makeBasis(new THREE.Vector3().setComponent(lateral[0],1),new THREE.Vector3().setComponent(lateral[1],1),normal)
    // X/Z lateral order for Y has negative handedness: map local Y to -Z.
    if (axis === 1) basis.makeBasis(new THREE.Vector3(1,0,0),new THREE.Vector3(0,0,-1),normal)
    rotation.setFromRotationMatrix(basis)
    for (const [side, charge] of [[-1,s.working_charge_C_m2],[1,s.counter_charge_C_m2]]) {
      const color = charge > 0 ? 0xf78166 : charge < 0 ? 0x58a6ff : 0x8b949e
      const face = new THREE.Mesh(new THREE.PlaneGeometry(s.width_nm,s.depth_nm),new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide,transparent:true,opacity:0.4,depthWrite:false}))
      face.position.setComponent(axis,side*s.gap_nm/2); face.quaternion.copy(rotation)
      face.name = side < 0 ? 'Working electrode schematic' : 'Counter electrode schematic'
      group.add(face)
      if (!charge) continue
      for (let u=0;u<4;u++) for (let v=0;v<4;v++) {
        const glyph = new THREE.Group()
        glyph.name = charge>0 ? 'Positive charge symbol' : 'Negative charge symbol'
        glyph.userData.chargeSign = Math.sign(charge)
        glyph.position.setComponent(axis,side*(s.gap_nm/2+0.45))
        glyph.position.setComponent(lateral[0],((u+.5)/4-.5)*s.width_nm)
        glyph.position.setComponent(lateral[1],((v+.5)/4-.5)*s.depth_nm)
        glyph.quaternion.copy(rotation)
        const size = Math.min(s.width_nm,s.depth_nm)/18
        const horizontal = new THREE.Mesh(new THREE.BoxGeometry(size,.07,.07),new THREE.MeshBasicMaterial({color}))
        glyph.add(horizontal)
        if(charge>0) glyph.add(new THREE.Mesh(new THREE.BoxGeometry(.07,size,.07),new THREE.MeshBasicMaterial({color})))
        group.add(glyph)
      }
    }
    group.visible=true
    const key = dims.join(',')
    if (camera && controls && key !== lastDimensions) {
      const radius = Math.hypot(...dims)/2 + 0.6
      const halfFov = Math.atan(Math.tan(camera.fov*Math.PI/360)*Math.min(1,camera.aspect))
      const direction = camera.position.clone().sub(controls.target).normalize()
      if (!direction.lengthSq()) direction.set(1,1,1).normalize()
      controls.target.set(0,0,0)
      camera.position.copy(direction.multiplyScalar(1.4*radius/Math.sin(halfFov)))
      camera.far = Math.max(camera.far, camera.position.length()+radius*4)
      camera.updateProjectionMatrix(); controls.update()
      lastDimensions = key
    }
  }
  window.addEventListener('nadoc:two-electrode-setup',update)
  return {dispose(){window.removeEventListener('nadoc:two-electrode-setup',update);clear();scene.remove(group)}}
}
