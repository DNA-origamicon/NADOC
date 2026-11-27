/** Rendering-only tetrahedra. Original sample values, linear interpolation, no splatting. */
import * as THREE from 'three'
import {adaptiveEMGrid} from './em_tetrahedra.js'
const row=(a,i,n)=>ArrayBuffer.isView(a)?a.subarray(i*n,(i+1)*n):a[i]
export function volumeGrid(result){
 if(result.sampling?.layout==='octree')return adaptiveEMGrid(result)
 const [nx,ny,nz]=result.shape,positions=[],tetrahedra=[]
 const at=(x,y,z)=>x*ny*nz+y*nz+z
 for(let x=0;x<nx;x++)for(let y=0;y<ny;y++)for(let z=0;z<nz;z++)positions.push([x,y,z].map((v,a)=>result.lower_nm[a]+v/(result.shape[a]-1)*(result.upper_nm[a]-result.lower_nm[a])))
 for(let x=0;x<nx-1;x++)for(let y=0;y<ny-1;y++)for(let z=0;z<nz-1;z++){
  const a=at(x,y,z),b=at(x+1,y,z),c=at(x,y+1,z),d=at(x+1,y+1,z),e=at(x,y,z+1),f=at(x+1,y,z+1),g=at(x,y+1,z+1),h=at(x+1,y+1,z+1)
  tetrahedra.push([a,b,d,h],[a,d,c,h],[a,c,g,h],[a,g,e,h],[a,e,f,h],[a,f,b,h])
 }
 return {positions,tetrahedra,values:Float64Array.from(result.intensity,(v,i)=>result.outside[i]&&Number.isFinite(v)?Math.max(0,v):0)}
}
export function prepareVolumeCells(result,grid,minimum=3){
 const arrays={p0:[],p1:[],p2:[],p3:[],b0:[],b1:[],b2:[],values:[]},bounds=new THREE.Box3(),matrix=new THREE.Matrix4()
 const count=ArrayBuffer.isView(grid.tetrahedra)?grid.tetrahedra.length/4:grid.tetrahedra.length
 const world=i=>{const p=row(grid.positions,i,3);return new THREE.Vector3(...result.origin_nm.map((v,a)=>v+p.reduce((s,x,b)=>s+x*result.basis[b][a],0)))}
 for(let t=0;t<count;t++){
  const ids=row(grid.tetrahedra,t,4),values=Array.from(ids,i=>grid.values[i])
  if(Math.max(...values)<=Math.max(1,minimum))continue
  const p=Array.from(ids,world)
  matrix.set(p[0].x-p[3].x,p[1].x-p[3].x,p[2].x-p[3].x,0,p[0].y-p[3].y,p[1].y-p[3].y,p[2].y-p[3].y,0,p[0].z-p[3].z,p[1].z-p[3].z,p[2].z-p[3].z,0,0,0,0,1)
  const determinant=matrix.determinant(),edges=matrix.elements
  const scale=Math.hypot(...edges.slice(0,3))*Math.hypot(...edges.slice(4,7))*Math.hypot(...edges.slice(8,11))
  // Coplanar adaptive-grid vertices can acquire a tiny nonzero determinant
  // from coordinate/pose roundoff. Inverting it creates enormous GPU planes
  // (and bright polygon artifacts). This relative double-precision tolerance
  // rejects numerical zero volume, not genuine thin cells or sampled peaks.
  if(!Number.isFinite(determinant)||Math.abs(determinant)<=64*Number.EPSILON*scale)continue
  // Consistent positive determinant makes the shared hull winding outward.
  if(determinant<0){[p[0],p[1]]=[p[1],p[0]];[values[0],values[1]]=[values[1],values[0]];const e=matrix.elements;for(let j=0;j<3;j++)[e[j],e[4+j]]=[e[4+j],e[j]]}
  matrix.invert();const e=matrix.elements
  for(let j=0;j<4;j++){arrays[`p${j}`].push(...p[j].toArray());bounds.expandByPoint(p[j])}
  for(let j=0;j<3;j++)arrays[`b${j}`].push(e[j],e[j+4],e[j+8],-e[j]*p[3].x-e[j+4]*p[3].y-e[j+8]*p[3].z)
  arrays.values.push(...values)
 }
 return {arrays:Object.fromEntries(Object.entries(arrays).map(([k,a])=>[k,new Float32Array(a)])),count:arrays.values.length/4,bounds}
}
/** Exact affine-tetrahedron ray interval, also a CPU correctness oracle. */
export function tetraRayInterval(planes,origin,direction,maxDistance=Infinity){
 const q=planes.map(p=>p[3]+p.slice(0,3).reduce((s,v,a)=>s+v*origin[a],0)),d=planes.map(p=>p.slice(0,3).reduce((s,v,a)=>s+v*direction[a],0))
 q.push(1-q.reduce((a,b)=>a+b,0));d.push(-d.reduce((a,b)=>a+b,0))
 let lo=0,hi=maxDistance
 for(let i=0;i<4;i++){if(Math.abs(d[i])<1e-12){if(q[i]<0)return null}else if(d[i]>0)lo=Math.max(lo,-q[i]/d[i]);else hi=Math.min(hi,-q[i]/d[i])}
 return hi>lo?[lo,hi]:null
}
