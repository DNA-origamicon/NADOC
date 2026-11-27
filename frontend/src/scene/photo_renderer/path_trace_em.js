import * as THREE from 'three'

/** Compact display projection. Doubles preserve legacy JS transform arithmetic;
 * the native worker rounds expanded vertices to float32 exactly as before. */
export function* compactEMCloud(points,camera,viewHeight){
  const positions=points.geometry.attributes.position,colors=points.geometry.attributes.color
  const start=points.geometry.drawRange.start,count=Math.min(positions.count-start,points.geometry.drawRange.count)
  if(!count||points.material.opacity<=0)return null
  const powerAttribute=points.geometry.attributes.emPower,power=powerAttribute?new Float32Array(count*3):null
  const centers=new Float64Array(count*3),radii=new Float64Array(count),rgb=new Float32Array(count*3)
  const center=new THREE.Vector3(),view=new THREE.Vector3(),fallback=points.material.color.toArray()
  for(let i=0;i<count;i++){
    center.fromBufferAttribute(positions,start+i).applyMatrix4(points.matrixWorld)
    view.copy(center).applyMatrix4(camera.matrixWorldInverse)
    const worldPerPixel=camera.isOrthographicCamera?(camera.top-camera.bottom)/camera.zoom/viewHeight
      :2*Math.max(camera.near,-view.z)*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))/camera.zoom/viewHeight
    center.toArray(centers,i*3);radii[i]=Math.max(1e-6,points.material.size*worldPerPixel/2)
    for(let k=0;k<3;k++)rgb[i*3+k]=colors?colors.getComponent(start+i,k):fallback[k]
    if(power)for(let k=0;k<3;k++)power[i*3+k]=powerAttribute.getComponent(start+i,k)
    if(i%1024===0)yield i/count
  }
  const geometry=new THREE.IcosahedronGeometry(1,0)
  const template={position:geometry.attributes.position.array,normal:geometry.attributes.normal.array}
  geometry.dispose()
  return {centers,radii,colors:rgb,...(power?{power}:{}),opacity:points.material.opacity,template}
}
