// @vitest-environment jsdom
import {it,expect,vi,afterEach} from 'vitest'
import * as T from 'three'
import {confirmEMRender} from './em_render_warning.js'
import {registerEMClear} from '../scene/em_export.js'
afterEach(()=>{document.body.innerHTML=''})
for(const choice of ['Continue','Clear field','Disable path tracing','Cancel'])it(`EM rendering warning: ${choice}`,async()=>{
 const scene=new T.Scene(),mesh=new T.Mesh(new T.BoxGeometry(),new T.MeshBasicMaterial());mesh.userData.emVolume=true;scene.add(mesh)
 const clear=vi.fn(),remove=registerEMClear(scene,clear),mode={getSettings:()=>({pathTracing:true}),setPathTracing:vi.fn()}
 const pending=confirmEMRender({scene,mode})
 const button=[...document.querySelectorAll('button')].find(b=>b.textContent===choice);expect(button).toBeTruthy();button.click()
 expect(await pending).toBe(({Continue:'continue','Clear field':'clear','Disable path tracing':'disable',Cancel:'cancel'})[choice])
 expect(clear).toHaveBeenCalledTimes(choice==='Clear field'?1:0);expect(mode.setPathTracing).toHaveBeenCalledTimes(choice==='Disable path tracing'?1:0)
 remove();mesh.geometry.dispose();mesh.material.dispose()
})
it('does not warn for an empty scene or tracing disabled',()=>{
 const scene=new T.Scene(),mode={getSettings:()=>({pathTracing:false})}
 expect(confirmEMRender({scene,mode})).toBe('continue');expect(document.querySelector('[role=dialog]')).toBeNull()
})
