import * as THREE from 'three'

/** Six face-adjacent lattice translations; excludes edge/corner neighbors. */
export function periodicOffsets(dimensions) {
  if(dimensions?.length!==3 || !dimensions.every(v=>Number.isFinite(v) && v>0))return []
  return dimensions.flatMap((length,axis)=>[-1,1].map(sign=>{
    const offset=[0,0,0];offset[axis]=sign*length;return offset
  }))
}

/** Sparse backbone ghosts share one buffer/material; never enter picking or topology. */
export function initPeriodicImages({scene,getEntries=()=>[]}={}) {
  const group=new THREE.Group()
  group.name='NAMD periodic images';group.userData.setupOnly=true;group.visible=false
  scene.add(group)
  let geometry=null,material=null
  function clear(){
    group.clear();geometry?.dispose();material?.dispose();geometry=material=null;group.visible=false
  }
  function update({detail:d}={}){
    clear()
    const offsets=periodicOffsets(d?.dimensions)
    if(!d?.periodicImages || !offsets.length)return
    const entries=getEntries().filter(e=>e.pos && [e.pos.x,e.pos.y,e.pos.z].every(Number.isFinite))
    if(!entries.length)return
    // Bound upload/draw cost for very large designs. These are shape cues, not atoms.
    const stride=Math.max(1,Math.ceil(entries.length/12000)),positions=[],samples=[]
    for(let i=0;i<entries.length;i+=stride){samples.push(entries[i]);positions.push(entries[i].pos.x,entries[i].pos.y,entries[i].pos.z)}
    geometry=new THREE.BufferGeometry()
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3))
    geometry.setAttribute('color',new THREE.Float32BufferAttribute(new Float32Array(positions.length),3))
    let lastFrame=-1
    const color=new THREE.Color()
    function sync(renderer){
      const frame=renderer?.info?.render?.frame
      if(frame!=null && frame===lastFrame)return
      lastFrame=frame
      const pos=geometry.attributes.position,colors=geometry.attributes.color
      samples.forEach((entry,i)=>{
        pos.setXYZ(i,entry.pos.x,entry.pos.y,entry.pos.z)
        if(entry.instMesh?.instanceColor)entry.instMesh.getColorAt(entry.id,color)
        else color.set(entry.defaultColor ?? 0x8ba8c4)
        colors.setXYZ(i,color.r,color.g,color.b)
      })
      pos.needsUpdate=true;colors.needsUpdate=true
    }
    sync()
    material=new THREE.PointsMaterial({vertexColors:true,size:.5,transparent:true,opacity:.32,depthWrite:false})
    offsets.forEach((offset,i)=>{
      const ghost=new THREE.Points(geometry,material)
      ghost.name=`Periodic image ${'XYZ'[Math.floor(i/2)]}${i%2?'+':'−'}`
      ghost.position.fromArray(offset)
      ghost.frustumCulled=false // Live visualization positions can leave the original bounds.
      ghost.onBeforeRender=sync
      ghost.raycast=()=>{} // No selection, hover, drag, or editor identity.
      group.add(ghost)
    })
    group.visible=true
  }
  const representationChanged=event=>{if(event.detail?.representation!=='full')clear()}
  window.addEventListener('nadoc:representation-change',representationChanged)
  window.addEventListener('nadoc:box-solvent-details',update)
  return {dispose(){window.removeEventListener('nadoc:representation-change',representationChanged);window.removeEventListener('nadoc:box-solvent-details',update);clear();scene.remove(group)}}
}
