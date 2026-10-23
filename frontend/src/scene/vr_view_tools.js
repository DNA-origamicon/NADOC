import { encodeTransformUpdate } from './vr_view_transform_stream.js'
import { createVRBatchEncoder } from './vr_view_batch_encoder.js'
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
const nextTask = () => new Promise(resolve => setTimeout(resolve, 0))

function displayFlags(doc) {
  const desktopOnlyLayout=['expanded','unfold'].some(key=>doc.querySelector(`[data-vt="${key}"]`)?.classList.contains('active'))
  return desktopOnlyLayout ? 256 : VR_VIEW_KEYS.reduce((v,k,i)=>v|(doc.querySelector(`[data-vt="${k}"]`)?.classList.contains('active')?viewBit(i):0),0) | (simulationViewActive(doc)?2048:0)
}

// Snapshot the actual displayed Three.js geometry, including instance colours,
// alpha, posed meshes and canvas labels. Native VR retains its own stereo camera.
function panelFingerprint(doc,message) {
  return JSON.stringify([displayFlags(doc),message,...VR_VIEW_KEYS.map(key=>{
    const b=doc.querySelector(`[data-vt="${key}"]`),style=b?(doc.defaultView??document.defaultView).getComputedStyle(b):null
    return [b?.querySelector('svg')?.outerHTML,style?.color,style?.backgroundColor,style?.borderColor]
  })])
}
async function capturePanel(doc,message,icons) {
  const panel=doc.createElement('canvas');panel.width=768;panel.height=768
  const c=panel.getContext('2d');c.fillStyle='#111111';c.fillRect(0,0,768,768)
  c.fillStyle='#e0eaff';c.font='bold 28px sans-serif';c.fillText('VIEW TOOLS',24,40)
  c.strokeStyle='#6e7681';c.strokeRect(620,8,124,44)
  c.fillStyle='#e0eaff';c.font='bold 20px sans-serif';c.fillText('CLOSE',647,37)
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
      const source=new XMLSerializer().serializeToString(icon)
      let im=icons.get(source)
      if(!im){im=new Image();im.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(source);await im.decode();if(icons.size>=32)icons.clear();icons.set(source,im)}
      c.drawImage(im,px+18,py+16,64,40)
    }
    c.fillStyle='#e0eaff';c.font='21px sans-serif';c.fillText(VR_VIEW_LABELS[i],px+18,py+82)
    c.fillStyle=flags&viewBit(i)?'#e0eaff':'#8592a5';c.font='bold 17px sans-serif';c.fillText(flags&viewBit(i)?'ON':'OFF',px+304,py+35)
  }
  c.fillStyle='#b6c7dc';c.font='18px sans-serif'
  drawViewToolMessage(c,message || (!(flags&256)?'Layout inspection. Restore Deform to edit.':'Left quiver: show / hide. Right quiver: scissors.'))
  c.strokeStyle='#6e7681';c.strokeRect(24,620,320,64)
  c.fillStyle='#e0eaff';c.font='bold 22px sans-serif';c.fillText('DOCK / FOLLOW',48,661)
  return panel
}

export async function captureVRView(scene, doc = document, message = '', panelOnly = false, reuseAtlas = null) {
  scene.updateMatrixWorld(true)
  const key=panelFingerprint(doc,message)
  if(reuseAtlas) {
    try {
      const revision=reuseAtlas.revision
      const changed=key!==reuseAtlas.panelKey
      let panel
      if(changed){panel=await capturePanel(doc,message,reuseAtlas.icons);reuseAtlas.updatePanel(panel,key)}
      const view=await captureVRGeometry(scene,doc,reuseAtlas,panelOnly)
      if(revision!==reuseAtlas.revision)return {...view,schema:5,pixels:reuseAtlas.pixels(),width:2048,height:2048}
      if(changed || panelOnly)return {...view,schema:panelOnly?9:8,pixels:reuseAtlas.panelPixels(),width:768,height:768}
      return view
    } catch(error) {
      if(error.message!=='View labels exceed VR atlas capacity' && error.message!=='View texture changed dimensions')throw error
      // Reclaim retired label slots by rebuilding from the current visible scene.
    }
  }
  const atlas=doc.createElement('canvas');atlas.width=2048;atlas.height=2048
  const ctx=atlas.getContext('2d'),textures=new Map(),icons=reuseAtlas?.icons??new Map()
  let x=0,y=0,row=0
  const allocate=(image)=>{
    const w=image.width,h=image.height
    if(w>2048||h>2048)throw new Error('View texture exceeds VR atlas size')
    if(x+w>2048){x=0;y+=row;row=0}
    if(y+h>2048)throw new Error('View labels exceed VR atlas capacity')
    ctx.drawImage(image,x,y,w,h);const r=[x/2048,y/2048,(x+w)/2048,(y+h)/2048]
    x+=w+2;row=Math.max(row,h+2);return r
  }
  const panel=await capturePanel(doc,message,icons),menu=allocate(panel)
  const mapUV=map=>{
    if(!map?.image)return null
    const old=textures.get(map.uuid),image=map.image
    if(old && (old.width!==image.width || old.height!==image.height))throw new Error('View texture changed dimensions')
    if(!old){textures.set(map.uuid,{uv:allocate(image),version:map.version,image,width:image.width,height:image.height});atlasState.revision++}
    else if(old.version!==map.version || old.image!==image){ctx.clearRect(old.uv[0]*2048,old.uv[1]*2048,image.width,image.height);ctx.drawImage(image,old.uv[0]*2048,old.uv[1]*2048);old.version=map.version;old.image=image;atlasState.revision++}
    return textures.get(map.uuid).uv
  }
  const atlasState={mapUV,menu,icons,panelKey:key,batchEncoder:createVRBatchEncoder(),revision:0,
    updatePanel(panel,key){ctx.clearRect(0,0,768,768);ctx.drawImage(panel,0,0);this.panelKey=key},
    panelPixels:()=>ctx.getImageData(0,0,768,768).data,
    pixels:()=>ctx.getImageData(0,0,2048,2048).data}
  const geometry=await captureVRGeometry(scene,doc,atlasState,panelOnly)
  return {...geometry,schema:5,pixels:atlasState.pixels(),width:2048,height:2048}
}

async function captureVRGeometry(scene, doc, atlasState, panelOnly = false) {
  const { mapUV, menu } = atlasState
  const flags=displayFlags(doc), desktopOnlyLayout=['expanded','unfold'].some(key=>doc.querySelector(`[data-vt="${key}"]`)?.classList.contains('active'))
  const triangles=[],lines=[],sprites=[],batches=[],annotations=new Map()
  const pos=new THREE.Vector3(),m=new THREE.Matrix4(),col=new THREE.Color(),scale=new THREE.Vector3(),quat=new THREE.Quaternion()
  const encoder=atlasState.batchEncoder ??= createVRBatchEncoder()
  const sphere=()=>atlasState.sphere ??= new THREE.SphereGeometry(1,24,16)
  const normal=new THREE.Vector3(),normalMatrix=new THREE.Matrix3()
  const add=(out,p,color,alpha,uv=null,n=null)=>{out.push(p.x,p.y,p.z,color.r,color.g,color.b,alpha,...(uv??[-1,-1]),...(n?n.toArray():[0,0,0]));if((triangles.length+lines.length)/12>MAX_VERTICES)throw new Error('VR display exceeds vertex budget')}
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
      } else if(o.isMesh && o.userData.vrAnnotation === true) {
        // Reserved UV (-2,-2): unlit, depth-independent annotation batch. Keep
        // the desktop meshes editable; share their templates only on the wire.
        if(o.matrixWorld.elements.every(Number.isFinite) && Math.abs(o.matrixWorld.determinant())>=1e-14) {
          const p=original.attributes.position
          for(const group of (original.groups.length?original.groups:[{start:0,count:original.index?.count??p?.count??0,materialIndex:0}])) {
            const mat=materials[group.materialIndex??0]??materials[0]
            if(!mat || mat.visible===false || mat.opacity<=0)continue
            const vertices=encoder.vertices(original,mat,group,null,original.groups.indexOf(group),o.userData.vrGlyph??true)
            if(!vertices.length)continue
            let batch=annotations.get(vertices)
            if(!batch){batch={name:'annotation',type:'InstancedMesh',vertices,instances:[]};annotations.set(vertices,batch)}
            batch.instances.push(...o.matrixWorld.elements,1,1,1,1)
          }
        }
      } else if(o.isInstancedMesh) {
        const spec=preparedImpostorSpec(materials[0]),g=spec?sphere():original,p=g.attributes.position
        if(p)for(const group of (g.groups.length?g.groups:[{start:0,count:g.index?.count??p.count,materialIndex:0}])) {
          const mat=materials[group.materialIndex??0]??materials[0]
          if(!mat||mat.visible===false||mat.opacity<=0)continue
          const uv=mapUV(mat.map)
          const vertices=encoder.vertices(g,mat,group,uv,g.groups.indexOf(group))
          const instances=encoder.instances(o,spec)
          if(vertices.length&&instances.length)batches.push({name:o.name,type:o.type,vertices,instances})
        }
      } else {
        const count=1
        for(let instance=0;instance<count;instance++) {
          m.copy(o.matrixWorld)
          const ia=original.attributes.instanceAlpha?.getX(instance)??1
          if(ia<=0 || Math.abs(m.determinant())<1e-14)continue
          const spec=preparedImpostorSpec(materials[0]);const g=spec?sphere():original
          if(spec)m.scale(new THREE.Vector3(spec.radius,spec.radius,spec.radius))
          const p=g.attributes.position;if(!p)continue
          normalMatrix.getNormalMatrix(m)
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
              const a=g.attributes.uv,n=o.isMesh&&g.attributes.normal?normal.fromBufferAttribute(g.attributes.normal,idx).applyMatrix3(normalMatrix).normalize():null;add(out,pos,colorAt(idx),mat.opacity*ia,uv&&a?[uv[0]+a.getX(idx)*(uv[2]-uv[0]),uv[1]+(1-a.getY(idx))*(uv[3]-uv[1])]:null,n)}
            if(o.isLineSegments)for(let k=start;k+1<end;k+=2){vertex(lines,k);vertex(lines,k+1)}
            else if(o.isLine) {for(let k=start;k+1<end;k++){vertex(lines,k);vertex(lines,k+1)}if(o.isLineLoop&&end>start){vertex(lines,end-1);vertex(lines,start)}}
            else if(o.isMesh)for(let k=start;k+2<end;k+=3){vertex(triangles,k);vertex(triangles,k+1);vertex(triangles,k+2)}
          }
        }
      }
    }
    for(const child of o.children)visit(child)
  }
  if(!panelOnly&&!desktopOnlyLayout&&flags!==256)visit(scene)
  for(const batch of annotations.values())batches.push({...batch,instances:new Float32Array(batch.instances)})
  return {schema:6,flags,menu,batches,triangles:new Float32Array(triangles),lines:new Float32Array(lines),sprites:new Float32Array(sprites),pixels:new Uint8Array(),width:0,height:0,atlasState}
}

export function encodeVRView(view,version,requestSequence=0) {
  const batches=view.batches??[]
  const schema=view.schema??4,stride=schema>=5?12:9
  const header=new Uint32Array([schema,version,view.flags,view.triangles.length/stride,view.lines.length/stride,view.sprites.length/15,view.width,view.height,batches.length,requestSequence])
  const parts=[new TextEncoder().encode('NADOCVT1'),header]
  if(schema>=8)parts.push(new Uint32Array([view.baseVersion]))
  parts.push(view.triangles,view.lines,view.sprites)
  for(const b of batches)parts.push(new Uint32Array([b.vertices.length/stride,b.instances.length/20]),b.vertices,b.instances)
  return new Blob([...parts,view.pixels])
}
export function createVRViewTools({scene,getState,onError=console.error,doc=document,capture=captureVRView,activateDeform=null,waitForTool=()=>{},subscribe=null}) {
  let busy=false,dirty=true,version=Math.floor(Math.random()*1e9)+1,last='',settle=0,stamp='',lastStampAt=0,message='',epoch=0,appliedSequence=0,lastGood=null,lastError=''
  const fingerprint=()=>[...VR_VIEW_KEYS,'expanded','unfold'].map(k=>doc.querySelector(`[data-vt="${k}"]`)?.classList.contains('active')?'1':'0').join('')
  const refresh = () => { dirty=true; settle=0;if(started)queueMicrotask(()=>void publish()) }
  subscribe?.((next,previous)=>{
    if(displayFlags(doc)!==256 && (next.currentGeometry!==previous.currentGeometry || next.currentDesign!==previous.currentDesign || next.currentHelixAxes!==previous.currentHelixAxes))refresh()
  })
  for (const event of ["nadoc:representation-change", "nadoc:simulation-display", "nadoc:md-heavy-status", "nadoc:oxdna-heavy-status"]) doc.defaultView?.addEventListener(event, refresh)
  let deliveryMilliseconds=0,controlPending=false,activating=false,started=false,atlasPatches=false,atlasInvalid=false
  let geometry,design,transformBase=null,transformBaseVersion=0,transformUpdates=false
  async function publish() {
    started=true
    const s=getState(),now=performance.now()
    // The canonical scene already handles edits in normal Deform mode. Its
    // view-tools stream contains only an unchanged tablet atlas (16 MiB), so
    // geometry changes must not rebuild, transfer and upload that atlas again.
    // Actual overlay/layout streams still follow every geometry/design change.
    const carriesScene=displayFlags(doc)!==256
    const cachedMap=!!doc.querySelector('#md-jobs-viz-body input[name="md-viz"][value="flex"]:checked,#oxdna-jobs-viz-body input[name="oxdna-viz"][value="flex"]:checked')
    if(!carriesScene)stamp=''
    // Simulation changes already publish explicit display/representation events.
    // A static cached map must not walk every atom again on the heartbeat.
    else if(doc.documentElement?.dataset.vrSimulationTrajectory !== 'true' && (dirty || (!cachedMap && now-lastStampAt>700))){stamp=broadcastFingerprint({scene});lastStampAt=now}
    const key=fingerprint()+simulationViewActive(doc)+stamp
    if(key!==last || (carriesScene&&(geometry!==s.currentGeometry || design!==s.currentDesign))){last=key;dirty=true}
    geometry=s.currentGeometry;design=s.currentDesign
    if(activating||busy||!dirty||performance.now()<settle){
      if(dirty)doc.defaultView?.__nadocVRPlaybackTrace?.({stage:'publish_wait',epoch_ms:performance.timeOrigin+performance.now(),reason:busy?'busy':'settle',wait_ms:Math.max(0,settle-performance.now())})
      return
    }
    busy=true;dirty=false;const publicationStart=performance.now(),generation=epoch,requestSequence=appliedSequence
    try {
      // Control delivery must not depend on a visible browser animation frame.
      await nextTask()
      const tracing=typeof doc.defaultView?.__nadocVRPlaybackTrace==='function'
      const stamp=(stage,extra={})=>{if(tracing)doc.defaultView.__nadocVRPlaybackTrace({stage,epoch_ms:performance.timeOrigin+performance.now(),version:version+1,...extra})}
      stamp('capture_start')
      const panelOnly=!!(atlasPatches && lastGood && displayFlags(doc)===256 && lastGood.flags===256)
      let view=await capture(scene,doc,message,panelOnly,!atlasInvalid&&(atlasPatches||doc.documentElement?.dataset.vrSimulationTrajectory==='true')?lastGood?.atlasState:null)
      if(view.schema>=8 && !atlasPatches)view={...view,schema:5,pixels:view.atlasState.pixels(),width:2048,height:2048}
      if(view.schema>=8)view.baseVersion=transformBaseVersion
      if(generation!==epoch)return
      stamp('capture_end')
      stamp('encode_start')
      ++version
      const update=transformUpdates ? encodeTransformUpdate(view,transformBase,transformBaseVersion,version,requestSequence,reason=>stamp('transform_fallback',{reason,version})) : null
      const body=update ?? encodeVRView(view,version,requestSequence)
      stamp('encode_end',{version})
      stamp('upload_start',{version,bytes:body.size,transforms:!!update})
      const response=await fetch('/api/vr/view-tools',{method:'POST',headers:{...docHeaders(),'Content-Type':'application/octet-stream'},body})
      stamp('upload_end',{version})
      if(!response.ok)throw new Error(await response.text())
      const receipt=await response.json?.()
      if(generation!==epoch)return
      transformUpdates=receipt?.transform_updates===true
      atlasPatches=receipt?.atlas_patches===true;atlasInvalid=false
      if(!update && view.schema!==9){transformBase=view;transformBaseVersion=version}
      deliveryMilliseconds=performance.now()-publicationStart
      lastGood=view.schema===9?{...lastGood,atlasState:view.atlasState}:view;lastError='';if(requestSequence===appliedSequence)controlPending=false
    }catch(error){
      transformBase=null;transformUpdates=false;atlasInvalid=true
      dirty=true;settle=performance.now()+2000
      if(generation!==epoch)return
      if(error.message!==lastError)onError(error.message)
      lastError=error.message
      // Preserve the last drawable scene, acknowledge the action, and leave
      // the tablet usable so the user can turn an unavailable overlay off.
      try {
        const panel=await capture(scene,doc,'View unavailable: '+error.message+'. Previous view retained.',true)
        let fallback={...panel,flags:256}
        if(lastGood) {
          const pixels=new Uint8Array(lastGood.pixels.length===2048*2048*4 ? lastGood.pixels : lastGood.atlasState.pixels())
          for(let y=0;y<768;y++)pixels.set(panel.pixels.subarray(y*2048*4,(y*2048+768)*4),y*2048*4)
          fallback={...lastGood,pixels,schema:5,width:2048,height:2048}
        }
        if(generation===epoch)await fetch('/api/vr/view-tools',{method:'POST',headers:{...docHeaders(),'Content-Type':'application/octet-stream'},body:encodeVRView(fallback,++version,requestSequence)})
      }catch{/* Retry after reconnect; the quiver can still stow the panel. */}
    }finally{busy=false;if(generation===epoch && dirty && performance.now()>=settle && (controlPending || doc.documentElement?.dataset.vrSimulationTrajectory==='true'))void publish()}
  }
  return {publish,refresh,async activate(index,sequence=0){
    const key=VR_VIEW_KEYS[index];if(!key)return
    appliedSequence=sequence;controlPending=true;activating=true
    const generation=epoch
    try {
      message=viewToolUnavailable(key,getState())
      if(!message) {
        const prior=new Set(doc.querySelectorAll('.toast--visible'))
        if(key==='deform' && activateDeform)await activateDeform()
        else doc.querySelector(`[data-vt="${key}"]`)?.click()
        await waitForTool(key)
        message=[...doc.querySelectorAll('.toast--visible')].filter(el=>!prior.has(el)).at(-1)?.querySelector('.toast-message')?.textContent??''
      }
    } catch(error) {message='View unavailable: '+error.message;onError(error.message)}
    finally {
      activating=false
      if(generation===epoch){dirty=true;settle=0;void publish()}
    }
  },reset(){epoch++;started=false;atlasPatches=false;atlasInvalid=false;controlPending=false;activating=false;deliveryMilliseconds=0;dirty=true;last='';message='';appliedSequence=0;lastGood=null;lastError='';transformBase=null;transformUpdates=false},get busy(){return busy},get delivery(){return {busy,milliseconds:deliveryMilliseconds}}}
}

export function viewToolUnavailable(key,state) {
  if(!VR_VIEW_KEYS.includes(key))return 'This view is not available in VR.'
  if(key!=='deform')return ''
  const design=state.currentDesign
  const posed=!!design?.deformations?.length || !!design?.cluster_transforms?.some(c=>
    c.translation?.some(v=>Math.abs(v)>1e-9) || c.rotation?.some((v,i)=>Math.abs(v-(i===3?1:0))>1e-9))
  if(state.unfoldActive)return 'Exit the desktop 2D layout before changing Deform.'
  if(!posed)return 'This design is already straight; there is no deformation to toggle.'
  return ''
}
