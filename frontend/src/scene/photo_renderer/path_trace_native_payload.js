import {traceLights} from './path_trace_snapshot.js'
import {nativeTraceVolumes} from './path_trace_volumes.js'

function packed(array){
  return new Uint8Array(array.buffer,array.byteOffset,array.byteLength)
}
function materialDTO(m){
  for(const [name,value] of Object.entries(m))if(value?.isTexture && name!=='emissiveMap')
    throw new Error('Experimental OptiX export supports solid materials and EM palettes; use WebGL for textured materials.')
  if(m.transmission>0 || m.sheen>0 || m.iridescence>0)
    throw new Error('Experimental OptiX export does not yet support this layered material. Use WebGL export.')
  const palette=m.emissiveMap
  if(palette && !palette.isDataTexture)throw new Error('OptiX requires a data texture for the EM palette.')
  return {color:m.color.toArray(),emission:m.emissive.toArray().map(v=>v*m.emissiveIntensity),
    roughness:m.roughness,metalness:m.metalness,opacity:m.opacity,
    clearcoat:m.clearcoat??0,clearcoatRoughness:m.clearcoatRoughness??.03,ior:m.ior??1.5,
    palette:palette?{data:packed(palette.image.data),width:palette.image.width,height:palette.image.height}:null}
}
function lightDTO(o){
  if(!o.isDirectionalLight && !o.isPointLight && !o.isSpotLight && !o.isRectAreaLight)throw new Error('Unsupported OptiX light.')
  return {type:o.type,position:o.position.toArray(),target:o.target?.position.toArray(),quaternion:o.quaternion.toArray(),
    color:o.color.toArray(),intensity:o.intensity,width:o.width,height:o.height,angle:o.angle,penumbra:o.penumbra}
}
/** Small camera-pinned light updates retain native meshes and environment pixels. */
export function nativeTraceLighting(scene){
  scene.updateMatrixWorld(true)
  return {lights:traceLights(scene).map(lightDTO),rotation:scene.environmentRotation.toArray().slice(0,3)}
}
/** Display-only DTO; never a NADOC document or an authoring command. */
export function nativeTracePayload(snapshot,environment,scene,settings){
  const meshes=[],lights=[]
  snapshot.root.traverse(o=>{
    if(o.isMesh){
      const g=o.geometry
      meshes.push({position:packed(g.attributes.position.array),normal:packed(g.attributes.normal.array),
        color:packed(g.attributes.color.array),uv:packed(g.attributes.uv.array),index:packed(g.index.array instanceof Uint32Array?g.index.array:new Uint32Array(g.index.array)),
        groups:g.groups,materials:[].concat(o.material).map(materialDTO)})
    }else if(o.isLight){
      lights.push(lightDTO(o))
    }
  })
  const volumes=nativeTraceVolumes(scene)
  return {meshes,lights,volumes,smoothEM:!!snapshot.smoothEM||volumes.length>0,emitters:snapshot.emitters??[],emSamples:snapshot.emSamples,environment:{data:packed(environment.image.data),width:environment.image.width,height:environment.image.height},
    rotation:scene.environmentRotation.toArray().slice(0,3),background:settings.bgColor??'#ffffff',transparent:settings.bgType==='transparent'}
}
