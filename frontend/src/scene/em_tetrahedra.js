/** Piecewise linear contours on the original adaptive samples. No averaging,
 * cell-volume weighting, or regular-grid resolution limit. */
import * as THREE from 'three'
const row=(a,i,n)=>ArrayBuffer.isView(a)?a.subarray(n*i,n*i+n):a[i]
export function adaptiveEMGrid(result){
 if(!result.display_tetrahedra)throw new Error('Recalculate the EM field to prepare sample-preserving smooth interpolation.')
 return {tetrahedra:result.display_tetrahedra,positions:result.sample_positions_nm,
  values:Float64Array.from(result.intensity,(v,i)=>result.outside[i]&&Number.isFinite(v)?Math.max(0,v):0)}
}
export function tetraContour(grid,level){
 const positions=[],{values,tetrahedra}=grid,count=ArrayBuffer.isView(tetrahedra)?tetrahedra.length/4:tetrahedra.length
 const point=i=>row(grid.positions,i,3)
 for(let t=0;t<count;t++){
  const ids=row(tetrahedra,t,4),inside=[],outside=[]
  for(const i of ids)(values[i]>=level?inside:outside).push(i)
  if(!inside.length||!outside.length)continue
  const edge=(a,b)=>{const p=point(a),q=point(b),f=(level-values[a])/(values[b]-values[a]);return [0,1,2].map(k=>p[k]+f*(q[k]-p[k]))}
  // Orient each triangle toward decreasing intensity, independently of tet winding.
  const direction=point(outside[0]).map((v,k)=>v-point(inside[0])[k])
  const emit=(a,b,c)=>{
   const u=b.map((v,k)=>v-a[k]),v=c.map((v,k)=>v-a[k])
   const normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
   if(normal.reduce((s,v,k)=>s+v*direction[k],0)<0)[b,c]=[c,b]
   positions.push(...a,...b,...c)
  }
  if(inside.length===1||outside.length===1){
   const solo=inside.length===1?inside:outside,others=inside.length===1?outside:inside
   emit(...others.map(i=>edge(solo[0],i)))
  }else{
   const [a,b]=inside,[c,d]=outside,p=edge(a,c),q=edge(a,d),r=edge(b,c),s=edge(b,d)
   emit(p,q,r);emit(q,s,r)
  }
 }
 const geometry=new THREE.BufferGeometry()
 geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3))
 geometry.computeVertexNormals()
 return geometry
}
