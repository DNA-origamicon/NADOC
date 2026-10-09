/** Individual duplex-axis tubes for the Connectivity origami preview. */
import * as THREE from 'three'

// Sampled helix axes are used directly: Catmull-Rom can overshoot the prescribed
// split section. Piecewise linear interpolation preserves the preview's joins.
class SampledPath extends THREE.Curve {
  constructor(points) { super(); this.points=points.map(p=>new THREE.Vector3(...p)) }
  getPoint(t,target=new THREE.Vector3()) {
    const x=Math.max(0,Math.min(1,t))*(this.points.length-1),i=Math.min(Math.floor(x),this.points.length-2)
    return target.copy(this.points[i]).lerp(this.points[i+1],x-i)
  }
}
export function createOrigamiPathOverlay(preview) {
  const group=new THREE.Group()
  group.name='Origami helix path preview';group.userData.origamiPathPreview=true
  group.userData.hb=preview.hb;group.userData.junctionHB=preview.junctionHB
  for(const path of preview.paths) {
    const curve=new SampledPath(path.points)
    const geometry=new THREE.TubeGeometry(curve,path.points.length-1,.9,8,false)
    const color=path.kind==='junction-extension'?0xffb454:((path.row+path.col)%2?0x929fff:0x58d9ce)
    const material=new THREE.MeshStandardMaterial({color,roughness:.55,metalness:.05})
    const mesh=new THREE.Mesh(geometry,material)
    mesh.userData.origamiHelixPath={edgeId:path.edgeId,helix:path.helix,kind:path.kind,junctionId:path.junctionId}
    mesh.raycast=()=>{};group.add(mesh)
    // Visible end caps distinguish local reinforcement from a fabricated strand
    // connection. They are helix-axis caps, not scaffold loop or staple claims.
    for(const end of [0,path.points.length-1]) {
      const cap=new THREE.Mesh(new THREE.SphereGeometry(.9,8,6),material.clone())
      cap.position.fromArray(path.points[end]);cap.raycast=()=>{};group.add(cap)
    }
  }
  return group
}
