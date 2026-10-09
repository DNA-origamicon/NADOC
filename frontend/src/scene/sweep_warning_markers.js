import * as THREE from 'three'

export const SWEEP_LIMIT_TEXT = 'Loop/skip limit is exceeded'
export function warningSegmentCenters(path, segments) {
  const sorted = [...new Set(segments)].filter(i=>path[i+1]).sort((a,b)=>a-b), centers=[]
  for(let begin=0;begin<sorted.length;) {
    let end=begin+1
    while(end<sorted.length && sorted[end]===sorted[end-1]+1) end++
    const i=sorted[Math.floor((begin+end-1)/2)]
    centers.push(path[i].map((v,k)=>(v+path[i+1][k])/2)); begin=end
  }
  return centers
}

/** Camera-facing warning icons shared by saved geometry and the live draft. */
export function createSweepWarningMarkers(scene, {canvas,getCamera,addFrameCallback,removeFrameCallback,getHelixCtrl,name='preview'}={}) {
  const group=new THREE.Group(); group.name=`sweep-warning-icons-${name}`; scene.add(group)
  const shape=new THREE.Shape(); shape.moveTo(-1,-.75);shape.lineTo(1,-.75);shape.lineTo(0,1);shape.closePath()
  const triangle=new THREE.ShapeGeometry(shape), stem=new THREE.PlaneGeometry(.15,.65),dot=new THREE.PlaneGeometry(.15,.15)
  const amber=new THREE.MeshBasicMaterial({color:0xf5a623,side:THREE.DoubleSide,depthTest:false,depthWrite:false})
  const ink=new THREE.MeshBasicMaterial({color:0x171b22,side:THREE.DoubleSide,depthTest:false,depthWrite:false})
  const ray=new THREE.Raycaster(),mouse=new THREE.Vector2()
  const tooltip=document.createElement('div'); tooltip.role='tooltip';tooltip.textContent=SWEEP_LIMIT_TEXT
  tooltip.style.cssText='position:fixed;display:none;pointer-events:none;z-index:10000;background:#171b22;color:#fff;border:1px solid #f5a623;border-radius:4px;padding:7px 10px;font:13px sans-serif'
  if(canvas)document.body.append(tooltip)
  let anchors=[]
  function hide(){tooltip.style.display='none'}
  function sync() {
    const camera=getCamera?.(); if(!camera)return
    const height=canvas?.getBoundingClientRect().height || 600, ctrl=getHelixCtrl?.()
    group.children.forEach((icon,i)=>{
      const anchor=anchors[i], positions=anchor.keys?.map(key=>ctrl?.lookupEntry?.(key)?.pos).filter(Boolean) ?? []
      if(positions.length)icon.position.copy(positions.reduce((sum,p)=>sum.add(p),new THREE.Vector3()).multiplyScalar(1/positions.length))
      else icon.position.fromArray(anchor.position)
      icon.quaternion.copy(camera.quaternion)
      const scale=camera.isPerspectiveCamera ? icon.position.distanceTo(camera.position)*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*32/height : (camera.top-camera.bottom)/camera.zoom*16/height
      icon.scale.setScalar(scale)
    })
  }
  function hover(event) {
    if(event.target!==canvas || event.buttons || !group.visible || !group.children.length){hide();return}
    sync();group.updateMatrixWorld(true)
    const rect=canvas.getBoundingClientRect();mouse.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1)
    ray.setFromCamera(mouse,getCamera())
    if(!ray.intersectObjects(group.children,false).length){hide();return}
    tooltip.style.left=`${Math.min(event.clientX+12,window.innerWidth-230)}px`;tooltip.style.top=`${event.clientY+14}px`;tooltip.style.display='block'
  }
  window.addEventListener('pointermove',hover,true);window.addEventListener('blur',hide)
  canvas?.addEventListener('pointerleave',hide);addFrameCallback?.(sync)
  return {
    set(values){anchors=values.map(v=>Array.isArray(v)?{position:v}:v);group.clear();hide()
      anchors.forEach(anchor=>{const icon=new THREE.Mesh(triangle,amber);icon.renderOrder=1100;icon.userData.helixIds=anchor.keys?.map(key=>key.split(':')[0]) ?? []
        const bar=new THREE.Mesh(stem,ink),point=new THREE.Mesh(dot,ink);bar.position.set(0,.15,.01);point.position.set(0,-.43,.01)
        bar.renderOrder=point.renderOrder=1101;icon.add(bar,point);group.add(icon)
      });sync()
    },
    dispose(){group.removeFromParent();triangle.dispose();stem.dispose();dot.dispose();amber.dispose();ink.dispose();tooltip.remove();window.removeEventListener('pointermove',hover,true);window.removeEventListener('blur',hide);canvas?.removeEventListener('pointerleave',hide);removeFrameCallback?.(sync)},
  }
}

export function initSavedSweepWarnings(scene,store,options) {
  const markers=createSweepWarningMarkers(scene,{...options,name:'saved'})
  function rebuild(state) {
    const geometry=state.currentGeometry ?? [], anchors=[]
    const byHelix=new Map()
    for(const n of geometry){if(!byHelix.has(n.helix_id))byHelix.set(n.helix_id,[]);byHelix.get(n.helix_id).push(n)}
    for(const op of state.currentDesign?.deformations ?? [])if(op.type==='sweep')for(const bp of op.params.warning_bps ?? []) {
      let distance=Infinity, found=[]
      for(const hid of op.affected_helix_ids ?? [])for(const n of byHelix.get(hid) ?? []) {
        const d=Math.abs(n.bp_index-bp)
        if(d<distance){distance=d;found=[]}if(d===distance)found.push(n)
      }
      if(!found.length)continue
      const position=[0,0,0]
      for(const n of found){const p=n.backbone_position;(Array.isArray(p)?p:[p.x,p.y,p.z]).forEach((v,k)=>position[k]+=v/found.length)}
      anchors.push({position,keys:found.map(n=>`${n.helix_id}:${n.bp_index}:${n.direction}`)})
    }
    markers.set(anchors)
  }
  const unsubscribe=store.subscribe((next,old)=>{if(next.currentDesign!==old.currentDesign || next.currentGeometry!==old.currentGeometry)rebuild(next)})
  rebuild(store.getState());return {dispose(){unsubscribe();markers.dispose()}}
}
