import * as THREE from 'three'
import { bakePreparedAssemblyInstances } from '../prepared_assembly_instances.js'
import { preparedImpostorSpec } from '../impostor_material.js'
import { instanceAlphaOnBeforeCompile } from '../instance_alpha.js'
import { selectionBaseCompiler } from '../selection_tint.js'
import { checkTraceGeometry } from './path_trace_limits.js'

export function traceLights(scene){
  const lights=[]
  scene.traverseVisible(object=>{
    if(!object.isLight || object.userData.emLight || object.isAmbientLight || object.isHemisphereLight)return
    const light=object.clone();light.position.setFromMatrixPosition(object.matrixWorld)
    if(object.target){light.target=object.target.clone();light.target.position.setFromMatrixPosition(object.target.matrixWorld);light.target.updateMatrixWorld()}
    lights.push(light)
  })
  return lights
}

// A disposable rendering projection, never an authored structure. No point thinning.
function* snapshotSteps(scene, camera, viewHeight, { maxTextureSize = Infinity } = {}) {
  const root = new THREE.Group(), owned = new Set()
  const own = value => { owned.add(value); return value }
  let triangles = 0, vertices = 0, bytes = 0, emSamples = 0
  let completedWork=0,totalWork=0
  const jobs=[]
  const dispose = () => { for (const value of owned) value.dispose(); owned.clear() }
  const budget = (count, vertexCount) => {
    triangles += count
    vertices += vertexCount
    bytes += vertexCount * 48 + count * 12
    checkTraceGeometry({vertices,triangles},maxTextureSize)
  }
  function material(source) {
    const compile=selectionBaseCompiler(source)
    if (source.clippingPlanes?.length || source.userData?.hullCutouts?.length || source.isShaderMaterial)
      throw new Error('This view uses a material or clipping effect that cannot yet be path traced. Use raster rendering for this view.')
    if (!preparedImpostorSpec(source) && compile!==THREE.Material.prototype.onBeforeCompile && compile!==instanceAlphaOnBeforeCompile)
      throw new Error('This view uses a custom display shader that cannot yet be path traced. Use raster rendering for this view.')
    let result
    if (source.isMeshStandardMaterial) result = source.clone()
    else {
      result = new THREE.MeshStandardMaterial({ roughness: source.shininess ? Math.sqrt(2 / (source.shininess + 2)) : 1 })
      for (const key of ['color','emissive','emissiveIntensity','map','normalMap','alphaMap','opacity','transparent','alphaTest','side','visible']) {
        if (source[key] !== undefined) result[key] = source[key]?.clone && source[key].isColor ? source[key].clone() : source[key]
      }
    }
    result.vertexColors = true
    return own(result)
  }
  function* bake(mesh, geometry, sourceMaterial, extraScale = 1) {
    const source = geometry.attributes.position
    if (!source) return
    const materials = (Array.isArray(sourceMaterial) ? sourceMaterial : [sourceMaterial]).map(material)
    if (materials.every(m => !m.visible || m.opacity <= 0)) return
    const matrices = [], alphas = [], colors = []
    const count = mesh.isInstancedMesh ? mesh.count : 1
    const matrix = new THREE.Matrix4(), color = new THREE.Color()
    for (let i = 0; i < count; i++) {
      const alpha = mesh.geometry.attributes.instanceAlpha?.getX(i) ?? 1
      if (alpha < .02) continue
      matrix.copy(mesh.matrixWorld)
      if (mesh.isInstancedMesh) { const local = new THREE.Matrix4(); mesh.getMatrixAt(i, local); matrix.multiply(local) }
      matrix.scale(new THREE.Vector3(extraScale, extraScale, extraScale))
      if (!matrix.elements.every(Number.isFinite) || Math.abs(matrix.determinant()) < 1e-14) continue
      matrices.push(matrix.clone()); alphas.push(alpha)
      color.setRGB(1,1,1)
      if (mesh.instanceColor) mesh.getColorAt(i, color)
      colors.push(color.clone())
    }
    completedWork+=source.count*(count-matrices.length)
    const start = geometry.drawRange.start, end = Math.min(geometry.index?.count ?? source.count, start + geometry.drawRange.count)
    const indexCount = Math.floor((end - start) / 3) * 3
    const n = source.count * matrices.length
    if (!n || !indexCount) return
    budget(indexCount / 3 * matrices.length,n)
    if (alphas.some(a=>a<1)) materials.forEach(m=>m.transparent=true)
    const positions = new Float32Array(n * 3), normals = new Float32Array(n * 3), uv = new Float32Array(n * 2), rgba = new Float32Array(n * 4)
    const indices = new Uint32Array(indexCount * matrices.length)
    const output = own(new THREE.BufferGeometry()), p = new THREE.Vector3(), normal = new THREE.Vector3(), normalMatrix = new THREE.Matrix3()
    const attrColor = geometry.attributes.color, attrNormal = geometry.attributes.normal, attrUV = geometry.attributes.uv
    for (let i = 0; i < matrices.length; i++) {
      normalMatrix.getNormalMatrix(matrices[i])
      for (let j = 0; j < source.count; j++) {
        const k = i * source.count + j
        p.fromBufferAttribute(source,j).applyMatrix4(matrices[i]).toArray(positions,k*3)
        if (attrNormal) normal.fromBufferAttribute(attrNormal,j).applyNormalMatrix(normalMatrix).toArray(normals,k*3)
        if (attrUV) { uv[k*2] = attrUV.getX(j); uv[k*2+1] = attrUV.getY(j) }
        color.copy(colors[i])
        if ((Array.isArray(sourceMaterial)?sourceMaterial.some(m=>m.vertexColors):sourceMaterial.vertexColors) && attrColor) color.multiply(new THREE.Color(attrColor.getX(j),attrColor.getY(j),attrColor.getZ(j)))
        color.toArray(rgba,k*4); rgba[k*4+3] = alphas[i] * (attrColor?.itemSize === 4 ? attrColor.getW(j) : 1)
        if((j+1)%8192===0)yield Math.min(.999,(completedWork+j+1)/Math.max(1,totalWork))
      }
      for (let j = 0; j < indexCount; j++) indices[i*indexCount+j] = i*source.count + (geometry.index?.getX(start+j) ?? start+j)
      if (matrices[i].determinant() < 0) for (let j=0;j<indexCount;j+=3) {
        const k=i*indexCount+j; [indices[k+1],indices[k+2]]=[indices[k+2],indices[k+1]]
      }
      completedWork+=source.count
      if(i%128===0)yield Math.min(.999,completedWork/Math.max(1,totalWork))
      if (materials.length > 1) for (const group of geometry.groups) {
        const lo=Math.max(start,group.start), hi=Math.min(end,group.start+group.count)
        if (hi>lo) output.addGroup(i*indexCount+lo-start,hi-lo,group.materialIndex)
      }
    }
    output.setAttribute('position',new THREE.BufferAttribute(positions,3))
    output.setAttribute('normal',new THREE.BufferAttribute(normals,3))
    output.setAttribute('uv',new THREE.BufferAttribute(uv,2))
    output.setAttribute('color',new THREE.BufferAttribute(rgba,4)); output.setIndex(new THREE.BufferAttribute(indices,1))
    if (!attrNormal) output.computeVertexNormals()
    const result = new THREE.Mesh(output,materials.length===1 ? materials[0] : materials)
    root.add(result)
    return result
  }
  function* emit(points) {
    const positions = points.geometry.attributes.position, colors = points.geometry.attributes.color
    const start = points.geometry.drawRange.start, count = Math.min(positions.count-start, points.geometry.drawRange.count)
    if (!count || points.material.opacity <= 0) return
    // Small 20-face spheres preserve source centers, screen dot diameter and palette.
    const template = own(new THREE.IcosahedronGeometry(1,0))
    checkTraceGeometry({vertices:vertices+count*template.attributes.position.count,triangles:triangles+count*20},maxTextureSize)
    const width = Math.ceil(Math.sqrt(count)), height = Math.ceil(count / width)
    const texels = new Float32Array(width*height*4)
    const texture = own(new THREE.DataTexture(texels,width,height,THREE.RGBAFormat,THREE.FloatType))
    texture.needsUpdate = true
    const source = own(new THREE.MeshStandardMaterial({ color:0x000000, emissive:0xffffff, emissiveIntensity:2,
      emissiveMap:texture, opacity:points.material.opacity, transparent:true, side:THREE.DoubleSide }))
    // One UV per emitter, shared by all its triangles. No per-sample lights/materials.
    const matrices = [], center = new THREE.Vector3(), view = new THREE.Vector3()
    for (let i=0;i<count;i++) {
      center.fromBufferAttribute(positions,start+i).applyMatrix4(points.matrixWorld)
      view.copy(center).applyMatrix4(camera.matrixWorldInverse)
      const worldPerPixel = camera.isOrthographicCamera ? (camera.top-camera.bottom)/camera.zoom/viewHeight
        : 2*Math.max(camera.near,-view.z)*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))/camera.zoom/viewHeight
      const radius = Math.max(1e-6, points.material.size * worldPerPixel / 2)
      matrices.push(new THREE.Matrix4().makeScale(radius,radius,radius).setPosition(center))
      for (let k=0;k<3;k++) texels[i*4+k] = colors ? colors.getComponent(start+i,k) : points.material.color.toArray()[k]
      texels[i*4+3]=1
    }
    const descriptor = {isInstancedMesh:true,count,geometry:template,matrixWorld:new THREE.Matrix4(),getMatrixAt:(i,m)=>m.copy(matrices[i])}
    const mesh = yield* bake(descriptor,template,source)
    const uv=mesh.geometry.attributes.uv, emitterVertices=template.attributes.position.count
    for(let i=0;i<count;i++) for(let j=0;j<emitterVertices;j++) uv.setXY(i*emitterVertices+j,((i%width)+.5)/width,(Math.floor(i/width)+.5)/height)
    mesh.userData.emEmitter=true; emSamples+=count
  }
  try {
    scene.updateMatrixWorld(true); camera.updateMatrixWorld(true)
    function visit(object) {
      if (!object.visible || object.isTransformControlsRoot || object.userData?.presentationSelection || object.userData?.vrAnnotation) return
      if (object.isLine || object.isLineSegments2 || object.isSprite || object instanceof THREE.ArrowHelper) return
      if (object.isPoints && object.userData.emSamples && object.material.visible) {
        totalWork+=Math.min(object.geometry.attributes.position.count-object.geometry.drawRange.start,object.geometry.drawRange.count)*60
        jobs.push(()=>emit(object))
      }
      else if (object.isMesh && !object.userData?.photoFloor) {
        if (object.isSkinnedMesh || object.isBatchedMesh || Object.keys(object.geometry.morphAttributes).length) throw new Error('Animated shader geometry is not supported by path tracing.')
        const mesh = bakePreparedAssemblyInstances(object), spec = preparedImpostorSpec(mesh.material)
        if (mesh===object && object.userData?.sharedInstanced) throw new Error('This shared display shader cannot yet be path traced.')
        if (mesh !== object) for (const m of Array.isArray(mesh.material)?mesh.material:[mesh.material]) own(m)
        const geometry = spec ? own(new THREE.SphereGeometry(1,12,8)) : mesh.geometry
        totalWork+=(geometry.attributes.position?.count??0)*(mesh.isInstancedMesh?mesh.count:1)
        jobs.push(()=>bake(mesh,geometry,mesh.material,spec?.radius ?? 1))
      } else if (object.isLight && !object.userData.emLight && !object.isAmbientLight && !object.isHemisphereLight) {
        const light = object.clone(); light.position.setFromMatrixPosition(object.matrixWorld)
        if(object.target) { light.target=object.target.clone(); light.target.position.setFromMatrixPosition(object.target.matrixWorld); light.target.updateMatrixWorld() }
        root.add(light)
      }
      object.children.forEach(visit)
    }
    visit(scene)
    for(const job of jobs)yield* job()
    root.updateMatrixWorld(true)
    return {root,triangles,vertices,bytes,emSamples,dispose}
  } catch(error) {
    dispose()
    if(error instanceof RangeError)throw new Error(`The browser could not allocate the path-tracing geometry (${(bytes/1048576).toFixed(1)} MiB of geometry buffers). ${error.message}`,{cause:error})
    throw error
  }
}


/** Keep the synchronous export API while allowing preview preparation to yield.
 * Progress counts finished instance batches, weighted by their vertex count. */
export function traceSnapshot(scene,camera,viewHeight,options){
  const steps=snapshotSteps(scene,camera,viewHeight,options)
  for(;;){const next=steps.next();if(next.done)return next.value}
}

export async function traceSnapshotAsync(scene,camera,viewHeight,options={}){
  const steps=snapshotSteps(scene,camera,viewHeight,options)
  let last=performance.now()
  options.onProgress?.(0)
  try{
    for(;;){
      options.signal?.throwIfAborted()
      const next=steps.next()
      if(next.done){options.onProgress?.(1);return next.value}
      options.onProgress?.(next.value)
      if(performance.now()-last>16){await new Promise(resolve=>setTimeout(resolve,0));last=performance.now()}
    }
  }catch(error){try{steps.throw(error)}catch{/* generator releases owned geometry */}throw error}
}
