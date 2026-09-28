import * as THREE from 'three'

/** Actual native menus and tool guides, in the avatar's tracking coordinate frame. */
export function createVRUI(root,{imageFactory=()=>new Image()}={}) {
  const group=new THREE.Group();group.name='vr-presenter-ui';root.add(group)
  const geometry=new THREE.BufferGeometry(),material=new THREE.LineBasicMaterial({vertexColors:true,toneMapped:false})
  const lines=new THREE.LineSegments(geometry,material);lines.frustumCulled=false;group.add(lines)
  const panels=new Map();let previous=null,disposed=false
  function remove(entry){entry.image.onload=entry.image.onerror=null;entry.mesh.removeFromParent();entry.mesh.geometry.dispose();entry.mesh.material.map?.dispose();entry.mesh.material.dispose()}
  function update(ui) {
    if(ui===previous)return;previous=ui
    const data=ui?.lines||[],positions=new Float32Array(data.length/2),colors=new Float32Array(data.length/2)
    for(let i=0,j=0;i<data.length;i+=6,j+=3){positions.set(data.slice(i,i+3),j);colors.set(data.slice(i+3,i+6),j)}
    if(geometry.getAttribute('position')?.array.length!==positions.length){
      geometry.dispose();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.BufferAttribute(colors,3))
    }else{geometry.getAttribute('position').array.set(positions);geometry.getAttribute('color').array.set(colors);geometry.getAttribute('position').needsUpdate=true;geometry.getAttribute('color').needsUpdate=true}
    lines.visible=!!data.length
    const wanted=new Set((ui?.panels||[]).map(p=>p.id))
    for(const [id,entry] of panels)if(!wanted.has(id)){remove(entry);panels.delete(id)}
    for(const panel of ui?.panels||[]) {
      let entry=panels.get(panel.id)
      if(!entry){
        const g=new THREE.BufferGeometry();g.setIndex([0,1,2,2,1,3]);g.setAttribute('uv',new THREE.Float32BufferAttribute([0,1,0,0,1,1,1,0],2))
        const mesh=new THREE.Mesh(g,new THREE.MeshBasicMaterial({side:THREE.DoubleSide,transparent:panel.id!=='desktop',alphaTest:panel.id==='desktop'?0:.02,toneMapped:false}))
        mesh.name=`vr-${panel.id}`;mesh.frustumCulled=false;mesh.visible=false;group.add(mesh)
        entry={mesh,png:null,image:imageFactory()};panels.set(panel.id,entry)
      }
      const position=entry.mesh.geometry.getAttribute('position')
      if(position){position.array.set(panel.corners);position.needsUpdate=true}
      else entry.mesh.geometry.setAttribute('position',new THREE.Float32BufferAttribute(panel.corners,3))
      if(entry.png!==panel.png){
        entry.png=panel.png;entry.image.onload=entry.image.onerror=null
        const image=imageFactory();entry.image=image
        image.onload=()=>{
          if(disposed||panels.get(panel.id)!==entry||entry.image!==image)return
          const texture=new THREE.Texture(image);texture.colorSpace=THREE.SRGBColorSpace;texture.needsUpdate=true
          entry.mesh.material.map?.dispose();entry.mesh.material.map=texture;entry.mesh.material.needsUpdate=true;entry.mesh.visible=true
        }
        image.onerror=()=>{if(entry.image===image)entry.mesh.visible=false}
        image.src=`data:image/png;base64,${panel.png}`
      }
    }
  }
  return {group,update,dispose(){disposed=true;for(const entry of panels.values())remove(entry);panels.clear();geometry.dispose();material.dispose();group.removeFromParent()}}
}
