import { broadcastFingerprint } from '../../viewer/broadcast_fingerprint.js'
import { preparedImpostorSpec } from '../impostor_material.js'

const compilers=new WeakMap()
let compilerId=0

/** Content, not upload counters or frame numbers, identifies a solved image. */
export function traceOutputKey({scene,camera,settings,width,height,viewHeight,ignoreTraceLighting=false,ignoreEM=false}) {
  scene.updateMatrixWorld(true);camera.updateMatrixWorld(true)
  const extra=[],materials=new Set()
  scene.traverseVisible(o=>{
    if(ignoreEM){for(let parent=o;parent;parent=parent.parent)if(parent.userData?.emField||parent.userData?.emSamples||parent.userData?.emLight)return}
    if(ignoreTraceLighting&&o.isAmbientLight)extra.push(o.color.toArray(),o.intensity)
    if(ignoreTraceLighting && (o.isLight || o.userData?.photoLightRig || o.userData?.photoFloor))return
    if(o.target){o.target.updateMatrixWorld(true);extra.push(o.target.matrixWorld.toArray())}
    extra.push(o.userData?.emVolumeColors,o.userData?.emSamples,o.userData?.emLight,o.userData?.photoFloor,o.userData?.presentationSelection,o.userData?.vrAnnotation)
    if(o.geometry?.groups?.length)extra.push(o.geometry.groups)
    for(const material of Array.isArray(o.material)?o.material:o.material?[o.material]:[]){
      if(materials.has(material))continue
      materials.add(material)
      const compiler=material.onBeforeCompile
      if(compiler && !compilers.has(compiler))compilers.set(compiler,++compilerId)
      extra.push(preparedImpostorSpec(material)?.radius,compilers.get(compiler))
      for(const value of Object.values(material)){
        if(value?.isVector2 || value?.isVector3 || value?.isMatrix3)extra.push(value.toArray())
        if(value?.isTexture)extra.push(value.uuid,value.offset.toArray(),value.repeat.toArray(),value.center.toArray(),
          value.rotation,value.matrix.toArray(),value.matrixAutoUpdate,value.wrapS,value.wrapT,value.flipY,value.channel,value.colorSpace)
      }
    }
  })
  return broadcastFingerprint({scene,view:settings,pane:[width,height,viewHeight,
    camera.matrixWorld.toArray(),camera.projectionMatrix.toArray(),camera.layers.mask,
    ignoreTraceLighting?null:scene.environmentRotation?.toArray(),extra]}, {ignoreTraceLighting,ignoreEM})
}

/** One bounded, pre-annotation output. Insets/text are composited afresh. */
export function createTraceOutputCache() {
  let key=null,canvas=null
  function clear(){key=null;if(canvas){canvas.width=0;canvas.height=0;canvas=null}}
  return {
    get(wanted){return wanted===key?canvas:null},
    put(next,source){
      // Optional reuse must not turn a successfully rendered large image into
      // an export failure just because a second canvas cannot be allocated.
      try{
        canvas??=document.createElement('canvas')
        canvas.width=source.width;canvas.height=source.height
        canvas.getContext('2d').drawImage(source,0,0);key=next
      }catch{clear()}
    },
    clear,
  }
}
