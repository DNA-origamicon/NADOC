import {it,expect,vi} from 'vitest'
import * as THREE from 'three'
import {compileTraceMaterial} from './path_trace_compile.js'
it('compiles the draw variant asynchronously and restores the live render target before waiting',async()=>{
  const live={},target={},camera=new THREE.OrthographicCamera(),material=new THREE.ShaderMaterial()
  material.setDefine=vi.fn();material.onBeforeRender=vi.fn()
  let finish,current=live
  const renderer={getRenderTarget:()=>current,setRenderTarget:t=>current=t,
    compileAsync:vi.fn((scene,c)=>{expect(current).toBe(target);expect(scene.children[0].material).toBe(material);expect(c.isOrthographicCamera).toBe(true);return new Promise(r=>finish=r)})}
  const status=vi.fn(),controller=new AbortController()
  const pending=compileTraceMaterial({renderer,material,camera,target,signal:controller.signal,onStatus:status})
  expect(current).toBe(live);expect(material.setDefine).toHaveBeenCalledWith('CAMERA_TYPE',1)
  expect(material.onBeforeRender).toHaveBeenCalledOnce();expect(status.mock.calls[0][0].label).toMatch(/Compiling/)
  controller.abort();finish();await expect(pending).rejects.toMatchObject({name:'AbortError'})
  expect(current).toBe(live);material.dispose()
})
