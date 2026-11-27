/** Disposable visualization of a sampled scalar field; no solver or document edits. */
import * as THREE from 'three'
import {emColorRGB} from './em_colors.js'
import {MarchingCubes} from 'three/addons/objects/MarchingCubes.js'
import {adaptiveEMGrid,tetraContour} from './em_tetrahedra.js'

/** Uniform grids retain every source node. Adaptive fields interpolate directly
 * on their original vertices, including the smallest refined hotspots. */
export function smoothEMGrid(result){
 if(result.sampling?.layout==='octree')return adaptiveEMGrid(result)
 const n=Math.max(9,...result.shape),size=n+4
 const values=new Float32Array(size**3)
 const span=result.upper_nm.map((v,a)=>v-result.lower_nm[a]),step=span.map(v=>v/(n-1))
 const at=(x,y,z)=>x+size*(y+size*z)
 const scalar=i=>result.outside[i]&&Number.isFinite(result.intensity[i])?Math.log10(1+Math.max(0,result.intensity[i])):0
  const [nx,ny,nz]=result.shape
  for(let z=0;z<n;z++)for(let y=0;y<n;y++)for(let x=0;x<n;x++){
   const q=[x,y,z].map((v,a)=>v*(result.shape[a]-1)/(n-1)),base=q.map(Math.floor),f=q.map((v,a)=>v-base[a]);let value=0
   for(let dz=0;dz<2;dz++)for(let dy=0;dy<2;dy++)for(let dx=0;dx<2;dx++){
    const i=Math.min(nx-1,base[0]+dx)*ny*nz+Math.min(ny-1,base[1]+dy)*nz+Math.min(nz-1,base[2]+dz)
    value+=scalar(i)*(dx?f[0]:1-f[0])*(dy?f[1]:1-f[1])*(dz?f[2]:1-f[2])
   }
   values[at(x+2,y+2,z+2)]=value
  }
 return {values,size,step}
}

/** Illustrative optical-depth transfer, referenced to absolute enhancement, not
 * the frame maximum. Split each band's depth between its entry/exit surfaces.
 * Differences telescope: adding contour layers does not add an opaque veil.
 * A 1x incident background contributes no extinction or emitted glow. */
export function emContourOpacity(lower,upper){
 const depth=value=>1.6*Math.log1p(Math.max(0,value-1)/99)/Math.LN2
 return -Math.expm1(-Math.max(0,depth(upper)-depth(lower))/2)
}

/** Thirty-two low-opacity contours approximate a continuous glow using portable standard
 * materials. No custom raster shader: the same geometry enters every tracer. */
export function createSmoothEMMeshes(result,grid,{minimum=3,maximum=100,colorMinimum=.1,colormap='jet',lighting='glow'}={}){
 const {values,size,step}=grid,low=Math.fround(Math.log10(1+Math.max(0,minimum)));let high=0
 for(const value of values)high=Math.max(high,grid.tetrahedra?Math.log10(1+value):value)
 if(high<=low)return []
 const marching=grid.tetrahedra?null:new MarchingCubes(size,{flatShading:false},false,false,5*(size-3)**3)
 if(marching)marching.field.set(values)
 const meshes=[],layers=32
 const basis=result.basis,matrix=new THREE.Matrix4().set(
  basis[0][0],basis[1][0],basis[2][0],result.origin_nm[0],
  basis[0][1],basis[1][1],basis[2][1],result.origin_nm[1],
  basis[0][2],basis[1][2],basis[2][2],result.origin_nm[2],0,0,0,1)
 for(let layer=0;layer<layers;layer++){
  const bandLow=low+(high-low)*layer/layers,bandHigh=low+(high-low)*(layer+1)/layers
  const opacity=emContourOpacity(10**bandLow-1,10**bandHigh-1)
  if(opacity===0)continue
  const level=low+(high-low)*(layer+.02)/layers
  let geometry
  if(grid.tetrahedra){
   geometry=tetraContour(grid,10**level-1)
   if(!geometry.attributes.position.count){geometry.dispose();continue}
  }else{
  marching.isolation=level;marching.update()
  if(!marching.count)continue
  const position=marching.positionArray.slice(0,marching.count*3)
  for(let i=0;i<position.length;i++){
   const a=i%3,index=(position[i]+1)*size/2-2
   position[i]=result.lower_nm[a]+Math.max(0,Math.min(size-5,index))*step[a]
  }
  geometry=new THREE.BufferGeometry()
  geometry.setAttribute('position',new THREE.BufferAttribute(position,3))
  const normals=marching.normalArray.slice(0,marching.count*3)
  for(let i=0;i<normals.length;i++)normals[i]/=step[i%3]
  geometry.setAttribute('normal',new THREE.BufferAttribute(normals,3));geometry.normalizeNormals()
  }
  geometry.applyMatrix4(matrix)
  // Reflecting frames require reversed winding, as well as transformed normals.
  if(matrix.determinant()<0){for(const attr of Object.values(geometry.attributes))for(let i=0;i<attr.count;i+=3)for(let a=0;a<3;a++){
   const j=(i+1)*3+a,k=(i+2)*3+a,v=attr.array[j];attr.array[j]=attr.array[k];attr.array[k]=v
  }}
  const color=new THREE.Color().setRGB(...emColorRGB(10**level-1,{maximum,colorMinimum,colormap}))
  const material=new THREE.MeshStandardMaterial({color:lighting==='off'?color:0x000000,emissive:lighting==='off'?0x000000:color,
   emissiveIntensity:2,roughness:1,transparent:true,opacity,depthWrite:false,side:THREE.DoubleSide,toneMapped:false})
  const mesh=new THREE.Mesh(geometry,material);mesh.userData.emSmooth=true;mesh.userData.emIntensityValue=10**level-1;mesh.userData.emOpacity=material.opacity;mesh.raycast=()=>{}
  meshes.push(mesh)
 }
 marching?.geometry.dispose()
 return meshes
}
