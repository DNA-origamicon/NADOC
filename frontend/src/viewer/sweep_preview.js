import * as THREE from 'three'
import { validateSweepPreview } from './sweep_preview_protocol.js'

/** Read-only transient overlay, separate from the saved molecular scene. */
export function createSweepPreview({scene,now=()=>performance.now()}) {
  const root=new THREE.Group();root.name='vr-sweep-preview';root.matrixAutoUpdate=false;root.visible=false;scene.add(root)
  const geometry=new THREE.BufferGeometry(), material=new THREE.LineBasicMaterial({vertexColors:true,toneMapped:false})
  const lines=new THREE.LineSegments(geometry,material);lines.frustumCulled=false;root.add(lines)
  const nodeGeometry=new THREE.SphereGeometry(1,12,8),nodeMaterial=new THREE.MeshBasicMaterial({color:0xffffff,toneMapped:false})
  const nodes=new THREE.InstancedMesh(nodeGeometry,nodeMaterial,256);nodes.frustumCulled=false;nodes.count=0;root.add(nodes)
  let previous=null,expires=0
  function clear(){previous=null;root.visible=false;nodes.count=0}
  function receive(value) {
    if(!value?.preview?.data){clear();return}
    expires=now()+Math.max(0,Math.min(3000,value.preview.expiresAt-value.serverTime))
    if(previous===value.preview.data)return
    let data
    try {data=validateSweepPreview(value.preview.data)} catch {clear();return}
    previous=value.preview.data
    const model=new THREE.Matrix4().fromArray(data.model)
    root.matrix.fromArray(data.trackingToSource);root.matrixWorldNeedsUpdate=true
    const position=[],color=[], green=[.3,1,.4],gold=[1,.87,.5],cyan=[.25,.7,.78]
    const world=p=>new THREE.Vector3(...p).applyMatrix4(model)
    const line=(a,b,c)=>{position.push(...a.toArray(),...b.toArray());color.push(...c,...c)}
    for(let i=1;i<data.path.length;i++)line(world(data.path[i-1]),world(data.path[i]),green)
    // Budget 2048 background cell rings plus at most 256 in the selected section.
    const stride=Math.max(1,Math.ceil(data.nodes.length*data.cells.length/2048))
    data.nodes.forEach((p,i)=>{
      const basis=data.frames[i],c=i===data.selected?gold:cyan
      const point=([x,y])=>world(p.map((v,j)=>v+basis[j]*x+basis[j+3]*y))
      data.outline.forEach((a,k)=>line(point(a),point(data.outline[(k+1)%data.outline.length]),c))
      for(let k=0;k<data.cells.length;k+=i===data.selected?1:stride){
        const [x,y]=data.cells[k]
        for(let j=0;j<16;j++){
          const a=j*Math.PI/8,b=(j+1)*Math.PI/8
          line(point([x+Math.cos(a),y+Math.sin(a)]),point([x+Math.cos(b),y+Math.sin(b)]),c)
        }
      }
      const m=new THREE.Matrix4().makeScale(data.radius,data.radius,data.radius);m.setPosition(world(p))
      nodes.setMatrixAt(i,m);nodes.setColorAt(i,new THREE.Color(...(i===data.selected?[1,.76,.18]:green)))
    })
    geometry.dispose();geometry.setAttribute('position',new THREE.Float32BufferAttribute(position,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(color,3))
    nodes.count=data.nodes.length;nodes.instanceMatrix.needsUpdate=true;if(nodes.instanceColor)nodes.instanceColor.needsUpdate=true
  }
  return {root,receive,clear,frame(){root.visible=!!previous&&now()<expires;if(root.parent!==scene)scene.add(root)},
    dispose(){root.removeFromParent();geometry.dispose();material.dispose();nodeGeometry.dispose();nodeMaterial.dispose()}}
}
