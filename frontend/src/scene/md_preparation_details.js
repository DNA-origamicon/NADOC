import * as THREE from 'three'

function label(text, {callout=false}={}) {
  const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d')
  if(!ctx)return new THREE.Group()
  const lines=text.split('\n')
  ctx.font='26px sans-serif'
  canvas.width=Math.min(640,Math.ceil(Math.max(...lines.map(line=>ctx.measureText(line).width)))+24);canvas.height=lines.length*40+20
  if(callout){
    ctx.fillStyle='rgba(13,17,23,0.92)';ctx.fillRect(0,0,canvas.width,canvas.height)
    ctx.strokeStyle='#61d9b4';ctx.lineWidth=3;ctx.strokeRect(1.5,1.5,canvas.width-3,canvas.height-3)
  }
  ctx.font='26px sans-serif'
  const widest=Math.max(...lines.map(line=>ctx.measureText(line).width))
  if(widest>616)ctx.font=`${Math.floor(26*616/widest)}px sans-serif`
  ctx.fillStyle='#61d9b4'
  lines.forEach((line,i)=>ctx.fillText(line,12,38+i*40))
  const texture=new THREE.CanvasTexture(canvas)
  const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,depthTest:false,depthWrite:false,transparent:true,sizeAttenuation:false}))
  sprite.scale.set(canvas.width*(callout?.00055:.00063),canvas.height*(callout?.00055:.00063),1)
  sprite.renderOrder=30
  sprite.userData.annotation=text
  return sprite
}

/** Display-only cell and solvent compartments; never drives molecular geometry. */
export function initPreparationDetails({scene,camera,controls,getEntries=()=>[]}={}) {
  const group=new THREE.Group();group.name='NAMD box and solvent details';group.visible=false;group.userData.setupOnly=true;scene.add(group)
  let lastSize=null, refreshLeader=()=>{}
  const onCameraChange=()=>refreshLeader()
  controls?.addEventListener?.('change',onCameraChange)
  function clear(){refreshLeader=()=>{};group.traverse(o=>{o.geometry?.dispose();o.material?.map?.dispose();o.material?.dispose()});group.clear();group.visible=false}
  function outline(size,center,color,name){
    const geometry=new THREE.BoxGeometry(...size)
    const mesh=new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color,transparent:true,opacity:.65,depthWrite:false}))
    geometry.dispose();mesh.position.copy(center);mesh.name=name;group.add(mesh)
  }
  function update({detail:d}={}){
    clear()
    if(!d?.enabled || !d.dimensions?.every(v=>Number.isFinite(v) && v>0)){lastSize=null;return}
    const size=d.dimensions,solvent=d.solvent || size
    let bounds=d.solute,center=new THREE.Vector3(...(d.center || [0,0,0]))
    if(!bounds && d.boundary!=='slab'){
      const box=new THREE.Box3()
      for(const e of getEntries())if(e.pos)box.expandByPoint(e.pos)
      if(!box.isEmpty()){bounds={min:box.min.toArray(),max:box.max.toArray()};box.getCenter(center)}
    }
    group.userData.dimensions=[...size];group.userData.preview=d
    outline(size,center,0x8b949e,'Simulation cell outline')
    if(d.boundary==='slab')outline(solvent,center,0x61d9b4,'Liquid compartment outline')
    for(let axis=0;axis<3;axis++)for(const sign of [-1,1]){
      const lateral=[0,1,2].filter(i=>i!==axis)
      const slab=d.boundary==='slab' && axis===d.normal_axis
      const face=new THREE.Mesh(new THREE.PlaneGeometry(size[lateral[0]],size[lateral[1]]),new THREE.MeshBasicMaterial({color:slab?0xd29922:0x58a6ff,transparent:true,opacity:.055,depthWrite:false,side:THREE.DoubleSide}))
      const normal=new THREE.Vector3().setComponent(axis,1)
      const u=new THREE.Vector3().setComponent(lateral[0],1),v=new THREE.Vector3().crossVectors(normal,u)
      face.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(u,v,normal))
      face.position.copy(center).setComponent(axis,center.getComponent(axis)+sign*size[axis]/2)
      face.name=`Boundary ${'XYZ'[axis]}${sign>0?'+':'−'} · ${slab?'slab-corrected periodic':'periodic'}`
      face.userData.boundary=slab?'slab':'periodic';group.add(face)
    }
    // Six translucent slabs show the actual gap from solute bounds to the solvent box.
    if(bounds){
      const min=center.clone().sub(new THREE.Vector3(...solvent).multiplyScalar(.5)),max=center.clone().add(new THREE.Vector3(...solvent).multiplyScalar(.5))
      for(let axis=0;axis<3;axis++)for(const sign of [-1,1]){
        const low=sign<0?min.getComponent(axis):bounds.max[axis],high=sign<0?bounds.min[axis]:max.getComponent(axis)
        if(high<=low)continue
        const extent=[...solvent];extent[axis]=high-low
        const slab=new THREE.Mesh(new THREE.BoxGeometry(...extent),new THREE.MeshBasicMaterial({color:0x61d9b4,transparent:true,opacity:.045,depthWrite:false}))
        slab.position.copy(center).setComponent(axis,(low+high)/2);slab.name='Water margin highlight';group.add(slab)
      }
    }else{
      const fill=new THREE.Mesh(new THREE.BoxGeometry(...solvent),new THREE.MeshBasicMaterial({color:0x61d9b4,transparent:true,opacity:.025,depthWrite:false}))
      fill.position.copy(center);fill.name='Solvent region highlight';group.add(fill)
    }
    function line(points,name){
      const o=new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:0x61d9b4,depthTest:false,depthWrite:false,transparent:true,opacity:.9}))
      o.renderOrder=30;o.name=name;group.add(o);return o
    }
    for(let axis=0;axis<3;axis++){
      const lateral=[0,1,2].filter(i=>i!==axis)
      const middle=center.clone()
      middle.setComponent(lateral[0],center.getComponent(lateral[0])-size[lateral[0]]/2)
      middle.setComponent(lateral[1],center.getComponent(lateral[1])+size[lateral[1]]/2)
      const offset=new THREE.Vector3().setComponent(lateral[0],-Math.max(.8,Math.min(...size)*.08))
      const edgeMiddle=middle.clone()
      middle.add(offset)
      const direction=new THREE.Vector3().setComponent(axis,1)
      const start=middle.clone().addScaledVector(direction,-size[axis]/2)
      const end=middle.clone().addScaledVector(direction,size[axis]/2)
      const tick=new THREE.Vector3().setComponent(lateral[0],Math.min(...size)*.018)
      const gap=Math.min(size[axis]*.2,1.5)
      line([edgeMiddle.clone().addScaledVector(direction,-size[axis]/2),start.clone().addScaledVector(offset,.2),
        edgeMiddle.clone().addScaledVector(direction,size[axis]/2),end.clone().addScaledVector(offset,.2)],`Dimension extension ${'XYZ'[axis]}`)
      line([start,middle.clone().addScaledVector(direction,-gap),middle.clone().addScaledVector(direction,gap),end,
        start.clone().sub(tick),start.clone().add(tick),end.clone().sub(tick),end.clone().add(tick)],`Dimension edge ${'XYZ'[axis]}`)
      const text=label(`${Number(size[axis].toFixed(2))}nm`)
      text.name=`Cell dimension ${'XYZ'[axis]}`;text.position.copy(middle);group.add(text)
    }
    const n=d.numbers
    const note=label(`NaCl ${d.na} mM · MgCl₂ ${d.mg} mM\nBulk ions ≈ Na⁺ ${n.na} · Mg²⁺ ${n.mg} · Cl⁻ ${n.cl}\n${d.temperature} ${d.temperatureLabel}\nEstimates exclude counterions / solute`,{callout:true})
    note.name='Solvent conditions callout';group.add(note)
    const anchor=center.clone().add(new THREE.Vector3(solvent[0]/2,solvent[1]/2,solvent[2]/2))
    const leader=line([anchor,anchor,anchor,anchor],'Solvent callout leader')
    refreshLeader=()=>{
      if(!camera){note.position.copy(anchor);return}
      camera.updateMatrixWorld()
      const target=anchor.clone().project(camera),aspect=camera.aspect || 1
      // Screen-space horizontal + 45-degree elbow, retained while orbiting.
      const x=Math.min(.85-note.scale.x/aspect,target.x+.16/aspect)
      const y=Math.min(.85-note.scale.y,target.y+.20)
      const edge=new THREE.Vector3(x,y,target.z)
      note.position.copy(new THREE.Vector3(x+note.scale.x/(2*aspect),y,target.z).unproject(camera))
      const dx=target.x-edge.x,dy=target.y-edge.y
      const diagonal=Math.min(Math.abs(dx)*aspect,Math.abs(dy))
      const elbow=new THREE.Vector3(target.x-Math.sign(dx)*diagonal/aspect,edge.y,target.z)
      const bend=new THREE.Vector3(target.x,edge.y+Math.sign(dy)*diagonal,target.z)
      leader.geometry.dispose()
      leader.geometry=new THREE.BufferGeometry().setFromPoints([edge.clone().unproject(camera),elbow.clone().unproject(camera),elbow.unproject(camera),bend.clone().unproject(camera),bend.unproject(camera),anchor])
    }
    group.visible=true
    const key=JSON.stringify([size,center.toArray()])
    if(camera && controls && key!==lastSize){
      const target=center.clone().add(new THREE.Vector3(0,2,0))
      const direction=camera.position.clone().sub(controls.target).normalize()
      if(!direction.lengthSq())direction.set(1,1,1).normalize()
      const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion)
      const up=new THREE.Vector3(0,1,0).applyQuaternion(camera.quaternion)
      const half=new THREE.Vector3(size[0]/2+4,size[1]/2+6,size[2]/2+4)
      const vertical=Math.tan(camera.fov*Math.PI/360),horizontal=vertical*camera.aspect
      let distance=0
      for(const x of [-1,1])for(const y of [-1,1])for(const z of [-1,1]){
        const corner=new THREE.Vector3(x*half.x,y*half.y,z*half.z)
        distance=Math.max(distance,corner.dot(direction)+Math.max(Math.abs(corner.dot(right))/horizontal,Math.abs(corner.dot(up))/vertical))
      }
      controls.target.copy(target);camera.position.copy(target).addScaledVector(direction,1.08*distance)
      camera.far=Math.max(camera.far,4*distance);camera.updateProjectionMatrix();controls.update();lastSize=key
    }
    refreshLeader()
  }
  window.addEventListener('nadoc:box-solvent-details',update)
  return {dispose(){controls?.removeEventListener?.('change',onCameraChange);window.removeEventListener('nadoc:box-solvent-details',update);clear();scene.remove(group)}}
}
