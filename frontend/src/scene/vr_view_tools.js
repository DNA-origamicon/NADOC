import { simulationViewActive } from './vr_simulations.js'
import * as THREE from 'three'
import { docHeaders } from '../shared/doc_id.js'
import { broadcastFingerprint } from '../viewer/broadcast_fingerprint.js'
import { preparedImpostorSpec } from './impostor_material.js'
import { drawViewToolMessage } from './vr_view_tools_panel.js'

export const VR_VIEW_KEYS = ['lengthHeatmap','sequences','undefinedBases','loopSkips','grid','overhangNames','clashes','deform']
export const VR_VIEW_LABELS = ['Length','Sequence','Undefined','Loop / skip','Grid','Overhang names','Clashes','Deform']
// Retain wire flag positions for the remaining view tools. Bits 7, 9 and 10 are retired.
const viewBit = i => 1 << (i < 7 ? i : i + 1)
const MAX_VERTICES = 4000000
const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve))

function displayFlags(doc) {
  const desktopOnlyLayout=['expanded','unfold','cadnano2d'].some(key=>doc.querySelector(`[data-vt="${key}"]`)?.classList.contains('active'))
  return desktopOnlyLayout ? 256 : VR_VIEW_KEYS.reduce((v,k,i)=>v|(doc.querySelector(`[data-vt="${k}"]`)?.classList.contains('active')?viewBit(i):0),0) | (simulationViewActive(doc)?2048:0)
}

// Snapshot the actual displayed Three.js geometry, including instance colours,
// alpha, posed meshes and canvas labels. Native VR retains its own stereo camera.
export async function captureVRView(scene, doc = document, message = '', panelOnly = false) {
  scene.updateMatrixWorld(true)
  const atlas = doc.createElement('canvas');atlas.width=2048;atlas.height=2048
  const ctx=atlas.getContext('2d'), textures=new Map()
  let x=0,y=0,row=0
  const allocate=(image,w=image.width,h=image.height)=>{
    if(w>2048||h>2048)throw new Error('View texture exceeds VR atlas size')
    if(x+w>2048){x=0;y+=row;row=0}
    if(y+h>2048)throw new Error('View labels exceed VR atlas capacity')
    ctx.drawImage(image,x,y,w,h);const r=[x/2048,y/2048,(x+w)/2048,(y+h)/2048]
    x+=w+2;row=Math.max(row,h+2);return r
  }
  const panel=doc.createElement('canvas');panel.width=768;panel.height=768
  const c=panel.getContext('2d');c.fillStyle='#111111';c.fillRect(0,0,768,768)
  c.fillStyle='#e0eaff';c.font='bold 28px sans-serif';c.fillText('VIEW TOOLS',24,40)
  const desktopOnlyLayout=['expanded','unfold','cadnano2d'].some(key=>doc.querySelector(`[data-vt="${key}"]`)?.classList.contains('active'))
  const flags=displayFlags(doc)
  for(let i=0;i<VR_VIEW_KEYS.length;i++) {
    const b=doc.querySelector(`[data-vt="${VR_VIEW_KEYS[i]}"]`),px=16+(i%2)*376,py=62+Math.floor(i/2)*112
    // Read the desktop's actual computed colors, including its active tint.
    // SVG children retain their explicit RGB values and gradient definitions.
    const desktopStyle=b?(doc.defaultView??document.defaultView).getComputedStyle(b):null
    c.fillStyle='#131313';c.fillRect(px,py,360,100)
    c.globalAlpha=.35;c.fillStyle=desktopStyle?.backgroundColor||'transparent';c.fillRect(px,py,360,100);c.globalAlpha=1
    c.strokeStyle=desktopStyle?.borderColor||'#6e7681';c.lineWidth=1;c.strokeRect(px+.5,py+.5,359,99)
    const svg=b?.querySelector('svg')?.outerHTML
    if(svg) {
      const icon=b.querySelector('svg').cloneNode(true);icon.setAttribute('xmlns','http://www.w3.org/2000/svg');icon.style.color=desktopStyle?.color||'#e6edf3'
      const im=new Image();im.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(icon))
      await im.decode();c.drawImage(im,px+18,py+16,64,40)
    }
    c.fillStyle='#e0eaff';c.font='21px sans-serif';c.fillText(VR_VIEW_LABELS[i],px+18,py+82)
    c.fillStyle=flags&viewBit(i)?'#e0eaff':'#8592a5';c.font='bold 17px sans-serif';c.fillText(flags&viewBit(i)?'ON':'OFF',px+304,py+35)
  }
  c.fillStyle='#b6c7dc';c.font='18px sans-serif'
  drawViewToolMessage(c,message || (!(flags&256)?'Layout inspection. Restore Deform to edit.':'Left quiver: show / hide. Right quiver: scissors.'))
  c.strokeStyle='#6e7681';c.strokeRect(24,620,320,64)
  c.fillStyle='#e0eaff';c.font='bold 22px sans-serif';c.fillText('DOCK / FOLLOW',48,661)
  const menu=allocate(panel)
  const mapUV=map=>{
    if(!map?.image)return null
    if(!textures.has(map.uuid))textures.set(map.uuid,allocate(map.image))
    return textures.get(map.uuid)
  }
  const triangles=[],lines=[],sprites=[],batches=[]
  const pos=new THREE.Vector3(),m=new THREE.Matrix4(),inst=new THREE.Matrix4(),col=new THREE.Color(),scale=new THREE.Vector3(),quat=new THREE.Quaternion()
  const sphere=new THREE.SphereGeometry(1,10,6)
  const add=(out,p,color,alpha,uv=null)=>{out.push(p.x,p.y,p.z,color.r,color.g,color.b,alpha,...(uv??[-1,-1]));if((triangles.length+lines.length)/9>MAX_VERTICES)throw new Error('VR display exceeds vertex budget')}
  const visit=o=>{
    if(!o.visible || o.isTransformControlsRoot)return
    if(o.isSprite && o.material?.visible!==false && o.material.opacity>0) {
      o.matrixWorld.decompose(pos,quat,scale);const uv=mapUV(o.material.map)
      if(uv)sprites.push(...pos.toArray(),scale.x,scale.y,...o.material.color.toArray(),o.material.opacity,...uv,...o.center.toArray())
    } else if(o.geometry && o.material) {
      const original=o.geometry,materials=Array.isArray(o.material)?o.material:[o.material]
      if(o.isLineSegments2) {
        const a=original.attributes.instanceStart,b=original.attributes.instanceEnd,mat=materials[0]
        if(a&&b&&mat.visible!==false)for(let i=0;i<a.count;i++)for(const [attr,colors] of [[a,original.attributes.instanceColorStart],[b,original.attributes.instanceColorEnd]]) {
          col.copy(mat.color)
          if(mat.vertexColors&&colors)col.multiply(new THREE.Color(colors.getX(i),colors.getY(i),colors.getZ(i)))
          add(lines,pos.fromBufferAttribute(attr,i).applyMatrix4(o.matrixWorld),col,mat.opacity)
        }
      } else if(o.isInstancedMesh) {
        const spec=preparedImpostorSpec(materials[0]),g=spec?sphere:original,p=g.attributes.position
        if(p)for(const group of (g.groups.length?g.groups:[{start:0,count:g.index?.count??p.count,materialIndex:0}])) {
          const mat=materials[group.materialIndex??0]??materials[0]
          if(!mat||mat.visible===false||mat.opacity<=0)continue
          const uv=mapUV(mat.map),vertices=[],instances=[]
          const start=Math.max(group.start,g.drawRange.start),end=Math.min(group.start+group.count,g.index?.count??p.count,g.drawRange.start+g.drawRange.count)
          for(let k=start;k+2<end;k+=3)for(let j=k;j<k+3;j++) {
            const idx=g.index?g.index.getX(j):j,a=g.attributes.uv
            col.copy(mat.color??new THREE.Color(1,1,1))
            if(mat.vertexColors&&g.attributes.color){const c=g.attributes.color;col.multiply(new THREE.Color(c.getX(idx),c.getY(idx),c.getZ(idx)))}
            add(vertices,pos.fromBufferAttribute(p,idx),col,mat.opacity,uv&&a?[uv[0]+a.getX(idx)*(uv[2]-uv[0]),uv[1]+(1-a.getY(idx))*(uv[3]-uv[1])]:null)
          }
          for(let i=0;i<o.count;i++) {
            const alpha=original.attributes.instanceAlpha?.getX(i)??1
            if(alpha<=0)continue
            o.getMatrixAt(i,inst);m.copy(o.matrixWorld).multiply(inst)
            // Cadnano suppresses some connector instances with degenerate poses.
            // They produce no desktop pixels and must not poison the binary feed.
            if(!m.elements.every(Number.isFinite)||Math.abs(m.determinant())<1e-14)continue
            if(spec)m.scale(new THREE.Vector3(spec.radius,spec.radius,spec.radius))
            col.setRGB(1,1,1);if(o.instanceColor)o.getColorAt(i,col)
            instances.push(...m.elements,col.r,col.g,col.b,alpha)
          }
          if(vertices.length&&instances.length)batches.push({name:o.name,type:o.type,vertices:new Float32Array(vertices),instances:new Float32Array(instances)})
        }
      } else {
        const count=1
        for(let instance=0;instance<count;instance++) {
          m.copy(o.matrixWorld);if(o.isInstancedMesh){o.getMatrixAt(instance,inst);m.multiply(inst)}
          const ia=original.attributes.instanceAlpha?.getX(instance)??1
          if(ia<=0 || Math.abs(m.determinant())<1e-14)continue
          const spec=preparedImpostorSpec(materials[0]);const g=spec?sphere:original
          if(spec)m.scale(new THREE.Vector3(spec.radius,spec.radius,spec.radius))
          const p=g.attributes.position;if(!p)continue
          const groups=g.groups.length?g.groups:[{start:0,count:g.index?.count??p.count,materialIndex:0}]
          for(const group of groups) {
            const mat=materials[group.materialIndex??0]??materials[0]
            if(!mat||mat.visible===false||mat.opacity<=0)continue
            const uv=mapUV(mat.map),start=Math.max(group.start,g.drawRange.start),end=Math.min(group.start+group.count,(g.index?.count??p.count),g.drawRange.start+g.drawRange.count)
            const base=mat.color??new THREE.Color(1,1,1)
            const colorAt=idx=>{
              col.copy(base)
              if(o.isInstancedMesh&&o.instanceColor){const cc=new THREE.Color();o.getColorAt(instance,cc);col.multiply(cc)}
              if(mat.vertexColors&&g.attributes.color){const a=g.attributes.color;col.multiply(new THREE.Color(a.getX(idx),a.getY(idx),a.getZ(idx)))}
              return col
            }
            const vertex=(out,k)=>{const idx=g.index?g.index.getX(k):k;pos.fromBufferAttribute(p,idx).applyMatrix4(m)
              const a=g.attributes.uv;add(out,pos,colorAt(idx),mat.opacity*ia,uv&&a?[uv[0]+a.getX(idx)*(uv[2]-uv[0]),uv[1]+(1-a.getY(idx))*(uv[3]-uv[1])]:null)}
            if(o.isLineSegments)for(let k=start;k+1<end;k+=2){vertex(lines,k);vertex(lines,k+1)}
            else if(o.isLine) {for(let k=start;k+1<end;k++){vertex(lines,k);vertex(lines,k+1)}if(o.isLineLoop&&end>start){vertex(lines,end-1);vertex(lines,start)}}
            else if(o.isMesh)for(let k=start;k+2<end;k+=3){vertex(triangles,k);vertex(triangles,k+1);vertex(triangles,k+2)}
          }
        }
      }
    }
    for(const child of o.children)visit(child)
  }
  if(!panelOnly&&!desktopOnlyLayout&&flags!==256)visit(scene);sphere.dispose()
  return {flags,menu,batches,triangles:new Float32Array(triangles),lines:new Float32Array(lines),sprites:new Float32Array(sprites),pixels:ctx.getImageData(0,0,2048,2048).data,width:2048,height:2048}
}

export function encodeVRView(view,version,requestSequence=0) {
  const batches=view.batches??[]
  const header=new Uint32Array([4,version,view.flags,view.triangles.length/9,view.lines.length/9,view.sprites.length/15,view.width,view.height,batches.length,requestSequence])
  const parts=[new TextEncoder().encode('NADOCVT1'),header,view.triangles,view.lines,view.sprites]
  for(const b of batches)parts.push(new Uint32Array([b.vertices.length/9,b.instances.length/20]),b.vertices,b.instances)
  return new Blob([...parts,view.pixels])
}
export function createVRViewTools({scene,getState,onError=console.error,doc=document}) {
  let busy=false,dirty=true,version=Math.floor(Math.random()*1e9)+1,last='',settle=0,stamp='',lastStampAt=0,message='',epoch=0,appliedSequence=0,lastGood=null,lastError=''
  const fingerprint=()=>[...VR_VIEW_KEYS,'expanded','unfold','cadnano2d'].map(k=>doc.querySelector(`[data-vt="${k}"]`)?.classList.contains('active')?'1':'0').join('')
  let geometry,design
  async function publish() {
    const s=getState(),now=performance.now()
    // The canonical scene already handles edits in normal Deform mode. Its
    // view-tools stream contains only an unchanged tablet atlas (16 MiB), so
    // geometry changes must not rebuild, transfer and upload that atlas again.
    // Actual overlay/layout streams still follow every geometry/design change.
    const carriesScene=displayFlags(doc)!==256
    if(!carriesScene)stamp=''
    else if(now-lastStampAt>700){stamp=broadcastFingerprint({scene});lastStampAt=now}
    const key=fingerprint()+simulationViewActive(doc)+stamp
    if(key!==last || (carriesScene&&(geometry!==s.currentGeometry || design!==s.currentDesign))){if(!dirty||!last)settle=now+1200;last=key;dirty=true}
    geometry=s.currentGeometry;design=s.currentDesign
    if(busy||!dirty||performance.now()<settle)return
    busy=true;dirty=false;const generation=epoch,requestSequence=appliedSequence
    try {
      await nextFrame();const view=await captureVRView(scene,doc,message)
      if(generation!==epoch)return
      const response=await fetch('/api/vr/view-tools',{method:'POST',headers:{...docHeaders(),'Content-Type':'application/octet-stream'},body:encodeVRView(view,++version,requestSequence)})
      if(!response.ok)throw new Error(await response.text())
      lastGood=view;lastError=''
    }catch(error){
      dirty=true;settle=performance.now()+2000
      if(generation!==epoch)return
      if(error.message!==lastError)onError(error.message)
      lastError=error.message
      // Preserve the last drawable scene, acknowledge the action, and leave
      // the tablet usable so the user can turn an unavailable overlay off.
      try {
        const panel=await captureVRView(scene,doc,'View unavailable: '+error.message+'. Previous view retained.',true)
        let fallback={...panel,flags:256}
        if(lastGood) {
          const pixels=new Uint8Array(lastGood.pixels)
          for(let y=0;y<768;y++)pixels.set(panel.pixels.subarray(y*2048*4,(y*2048+768)*4),y*2048*4)
          fallback={...lastGood,pixels}
        }
        if(generation===epoch)await fetch('/api/vr/view-tools',{method:'POST',headers:{...docHeaders(),'Content-Type':'application/octet-stream'},body:encodeVRView(fallback,++version,requestSequence)})
      }catch{/* Retry after reconnect; the quiver can still stow the panel. */}
    }finally{busy=false}
  }
  return {publish,async activate(index,sequence=0){
    appliedSequence=sequence
    const key=VR_VIEW_KEYS[index];if(!key)return
    message=viewToolUnavailable(key,getState())
    if(!message) {
      const prior=new Set(doc.querySelectorAll('.toast--visible'))
      doc.querySelector(`[data-vt="${key}"]`)?.click()
      message=[...doc.querySelectorAll('.toast--visible')].filter(el=>!prior.has(el)).at(-1)?.querySelector('.toast-message')?.textContent??''
    }
    dirty=true;settle=performance.now()+1500
  },reset(){epoch++;dirty=true;last='';message='';appliedSequence=0;lastGood=null;lastError=''},get busy(){return busy}}
}

export function viewToolUnavailable(key,state) {
  if(!VR_VIEW_KEYS.includes(key))return 'This view is not available in VR.'
  if(key!=='deform')return ''
  const design=state.currentDesign
  const posed=!!design?.deformations?.length || !!design?.cluster_transforms?.some(c=>
    c.translation?.some(v=>Math.abs(v)>1e-9) || c.rotation?.some((v,i)=>Math.abs(v-(i===3?1:0))>1e-9))
  if(state.unfoldActive||state.cadnanoActive)return 'Exit the desktop 2D layout before changing Deform.'
  if(!posed)return 'This design is already straight; there is no deformation to toggle.'
  return ''
}
