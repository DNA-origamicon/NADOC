/** Original adaptive tetrahedra for native reflected-ray volume emission.
 * Camera radiance remains in the shared compositor; never bake it twice. */
export function nativeTraceVolumes(scene){
 const volumes=[]
 scene.traverseVisible(mesh=>{
  if(!mesh.userData.emVolume||!mesh.material.visible||mesh.material.opacity<=0)return
  const u=mesh.material.uniforms,arrays=mesh.emVolumeCells
  const packed=a=>new Uint8Array(a.buffer,a.byteOffset,a.byteLength)
  volumes.push({positions:[0,1,2,3].map(i=>packed(arrays[`p${i}`])),values:packed(arrays.values),
   palette:packed(u.palette.value.image.data),minimum:u.cutoff.value,
   colorLow:u.colorLow.value,colorHigh:u.colorHigh.value,weight:mesh.material.opacity})
 })
 return volumes
}
