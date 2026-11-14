import {it,expect} from 'vitest'
import * as THREE from 'three'
import {initZoomVolumeHighlight} from './zoom_volume_highlight.js'
it('owns independent overlays, follows positions and exact MD atoms, and disposes',()=>{
 const scene=new THREE.Scene(),a=initZoomVolumeHighlight(scene,'a'),b=initZoomVolumeHighlight(scene,'b')
 const pos=new THREE.Vector3(1,2,3),entry={nuc:{helix_id:'h',bp_index:1,direction:'FORWARD'},pos}
 a.add([entry]);b.add([entry],new THREE.Matrix4().makeTranslation(10,0,0))
 a.update(true);b.update(false)
 expect(scene.getObjectByName('Zoom highlight a').visible).toBe(true)
 expect(scene.getObjectByName('Zoom highlight b').visible).toBe(false)
 const point=name=>{const m=new THREE.Matrix4();scene.getObjectByName(name).getMatrixAt(0,m);return new THREE.Vector3().setFromMatrixPosition(m).toArray()}
 pos.set(4,5,6);a.update(true);expect(point('Zoom highlight atoms a')).toEqual([4,5,6])
 a.update(true,new Map([['h:1:FORWARD:P',[8,8,8]],['h:1:FORWARD:C1',[10,10,10]]]))
 expect(point('Zoom highlight atoms a')).toEqual([9,9,9])
 b.update(true);expect(point('Zoom highlight atoms b')).toEqual([14,5,6])
 a.dispose();expect(scene.getObjectByName('Zoom highlight a')).toBeUndefined()
 expect(scene.getObjectByName('Zoom highlight b')).toBeTruthy();b.dispose();expect(scene.children).toHaveLength(0)
})
