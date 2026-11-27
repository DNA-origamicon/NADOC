import {expect,it} from 'vitest'
import {volumeGrid,prepareVolumeCells,tetraRayInterval} from './em_volume_data.js'
import {createEMVolume,updateVolumeColors} from './em_volume.js'
import {createEMFieldOverlay} from './em_field.js'
import {traceSnapshot,traceLights} from './photo_renderer/path_trace_snapshot.js'
import * as THREE from 'three'
const field=()=>({sampling:{layout:'octree'},sample_positions_nm:[[1,0,0],[0,1,0],[0,0,1],[0,0,0]],display_tetrahedra:[[0,1,2,3]],intensity:[100,1,1,1],outside:[1,1,1,1],cell_sizes_nm:Array(4).fill([1,1,1]),shape:[4,1,1],lower_nm:[0,0,0],upper_nm:[1,1,1],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]]})
it('retains a narrow adaptive peak and exact linear barycentric coefficients',()=>{
 const data=field();data.sample_positions_nm[0][0]=.001
 const {arrays,count}=prepareVolumeCells(data,volumeGrid(data),3)
 expect(count).toBe(1);expect(Array.from(arrays.values)).toEqual([100,1,1,1])
 const planes=[arrays.b0,arrays.b1,arrays.b2].map(a=>Array.from(a))
 const hit=tetraRayInterval(planes,[-1,.1,.1],[1,0,0])
 expect(hit[0]).toBeCloseTo(1,8);expect(hit[1]).toBeCloseTo(1.0008,8)
 expect(tetraRayInterval(planes,[-1,2,.1],[1,0,0])).toBe(null)
 expect(tetraRayInterval(planes,[-1,.1,.1],[1,0,0],.5)).toBe(null)
 expect(tetraRayInterval(planes,[-1,.1,.1],[1,0,0],1.0004)[1]).toBe(1.0004)
})
it('handles camera inside, masks, reflections, and leaves the source untouched',()=>{
 const data=field(),before=JSON.stringify(data),grid=volumeGrid(data)
 const {arrays}=prepareVolumeCells(data,grid,3),planes=[arrays.b0,arrays.b1,arrays.b2].map(a=>Array.from(a))
 expect(tetraRayInterval(planes,[.1,.1,.1],[1,0,0])).toEqual([0,.7])
 expect(prepareVolumeCells(data,grid,101).count).toBe(0)
 expect(volumeGrid({...data,outside:[0,1,1,1]}).values[0]).toBe(0)
 expect(JSON.stringify(data)).toBe(before)
 data.basis[0][0]=-1;data.origin_nm=[5,6,7]
 const reflected=prepareVolumeCells(data,grid,3)
 expect(reflected.bounds.min.toArray()).toEqual([4,6,7]);expect(reflected.bounds.max.toArray()).toEqual([5,7,8])
})
it('preserves every uniform sample with conforming tetrahedra, independent of grid density',()=>{
 const data={...field(),sampling:null,shape:[3,3,3],intensity:Array(27).fill(1),outside:Array(27).fill(1)};data.intensity[13]=100
 const grid=volumeGrid(data)
 expect(grid.positions.length).toBe(27);expect(grid.tetrahedra.length).toBe(48);expect(grid.values[13]).toBe(100)
 const used=new Set(grid.tetrahedra.flat());expect(used.size).toBe(27)
})
it('updates the palette without rebuilding cells and disposes context resources',()=>{
 const data=field(),[mesh]=createEMVolume(data,volumeGrid(data)),geometry=mesh.geometry
 const palette=mesh.material.uniforms.palette.value;let disposed=false;palette.addEventListener('dispose',()=>disposed=true)
 const before=palette.image.data.slice();updateVolumeColors(mesh,{colormap:'magma'})
 expect(mesh.geometry).toBe(geometry);expect(palette.image.data).not.toEqual(before)
 mesh.material.dispose();geometry.dispose();expect(disposed).toBe(true)
})
it('excludes volume hulls from tracing and preserves optional surface lights and crossfade weights',()=>{
 const scene=new THREE.Scene(),overlay=createEMFieldOverlay(scene),data=field(),camera=new THREE.PerspectiveCamera()
 overlay.show(data,{mode:'smooth',minimum:3,lighting:'illuminate'})
 const mesh=scene.children[0].children.find(o=>o.userData.emVolume)
 expect(mesh.userData.emCellCount).toBe(1);overlay.weight(.4);expect(mesh.material.opacity).toBe(.4)
 expect(traceLights(scene).length).toBeGreaterThan(0)
 const snapshot=traceSnapshot(scene,camera,100)
 expect(snapshot.triangles).toBe(0);expect(snapshot.root.children.some(o=>o.isMesh)).toBe(false)
 snapshot.dispose();overlay.dispose()
})
it('invalidates cached integration for camera, geometry, visibility and palette, but not field opacity',async()=>{
 const {volumeViewKey}=await import('./em_volume_cache.js')
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),size=new THREE.Vector2(32,32),palette={version:0},renderer={}
 const object=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());scene.add(object)
 const field=new THREE.Group();field.userData.emField=true;scene.add(field)
 const volume=new THREE.Mesh(new THREE.PlaneGeometry(),new THREE.MeshBasicMaterial());field.add(volume)
 const key=()=>{scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);return volumeViewKey(scene,camera,size,palette,renderer)}
 let before=key();volume.material.opacity=.4;expect(key()).toBe(before)
 camera.position.x=1;expect(key()).not.toBe(before);before=key()
 object.position.x=1;expect(key()).not.toBe(before);before=key()
 object.geometry.attributes.position.setX(0,5);object.geometry.attributes.position.needsUpdate=true;expect(key()).not.toBe(before);before=key()
 object.visible=false;expect(key()).not.toBe(before);before=key()
 palette.version++;expect(key()).not.toBe(before)
 for(const mesh of [object,volume]){mesh.geometry.dispose();mesh.material.dispose()}
})

it('rejects roundoff-volume coplanar cells before they generate unstable GPU planes',()=>{
 const data=field();data.sample_positions_nm=[[0,0,0],[1,0,0],[1,1,1e-15],[0,1,0]]
 data.intensity=[119,10,3,20];data.origin_nm=[11.2,14.5,6]
 const rotation=new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(.13,.23,.31))
 data.basis=[new THREE.Vector3(1,0,0),new THREE.Vector3(0,1,0),new THREE.Vector3(0,0,1)].map(p=>p.applyMatrix4(rotation).toArray())
 expect(prepareVolumeCells(data,volumeGrid(data),3).count).toBe(0)
 // A genuine thin cell remains part of the interpolation, with its peak intact.
 data.sample_positions_nm[2][2]=.0001
 const cells=prepareVolumeCells(data,volumeGrid(data),3)
 expect(cells.count).toBe(1);expect(Math.max(...cells.arrays.values)).toBe(119)
})
