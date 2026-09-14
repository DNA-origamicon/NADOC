import {it,expect} from 'vitest'
import * as THREE from 'three'
import {initNamdPegCoatingPreview} from './namd_peg_coating_preview.js'
it('shows only stored graft sites, toggles visibility, and removes the preview',()=>{
 const scene=new THREE.Scene(),ui=initNamdPegCoatingPreview({scene})
 const coating={preview:{graft_sites_nm:[[1,2,3],[4,5,6]]}}
 const send=detail=>window.dispatchEvent(new CustomEvent('nadoc:namd-peg-coating',{detail}))
 send({coating,visible:true})
 expect(scene.children[0].visible).toBe(false)
 expect(scene.children[0].children).toHaveLength(0)
 window.dispatchEvent(new CustomEvent('nadoc:namd-surface-selection',{detail:{enabled:true,jobId:'peg',coating}}))
 expect([...scene.children[0].children[0].geometry.attributes.position.array]).toEqual([1,2,3,4,5,6])
 send({coating,visible:false});expect(scene.children[0].visible).toBe(false)
 window.dispatchEvent(new CustomEvent('nadoc:namd-surface-selection',{detail:{enabled:false}}));expect(scene.children[0].children).toHaveLength(0)
 ui.dispose();expect(scene.children).toHaveLength(0)
})
