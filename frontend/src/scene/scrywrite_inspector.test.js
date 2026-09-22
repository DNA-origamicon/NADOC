import {describe,it,expect} from 'vitest'
import {project,corners,rotate,targets} from '../../scrywrite/inspector/geometry.js'
const eye={position:[0,0,0],orientation_xyzw:[0,0,0,1],fov_left_right_up_down:[-Math.PI/4,Math.PI/4,Math.PI/4,-Math.PI/4],width:100,height:100}
describe('captured-eye inspector projection',()=>{
 it('projects front center and rejects points behind eye',()=>{expect(project([0,0,-1],eye)).toEqual([50,50]);expect(project([0,0,1],eye)).toBeNull();expect(project([0,1,-1],eye)[1]).toBeCloseTo(0)})
 it('rotates geometry and emits actual rectangle corners',()=>{expect(rotate([0,0,0,1],[1,2,3])).toEqual([1,2,3]);expect(corners({position:[0,0,-1],hit_half_right:[1,0,0],hit_half_up:[0,1,0]})).toEqual([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1]])})
 it('separates menu and lattice identities',()=>{const t=targets({menu:'tools',controls:[{label:'BACK'}],extrude:{visible_cells:[{row:0,column:1,position:[0,0,0]}]}});expect(t.map(v=>v.key)).toEqual(['tools:BACK','cell:0,1'])})
})
