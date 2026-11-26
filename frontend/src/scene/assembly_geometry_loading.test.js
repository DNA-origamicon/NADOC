import {it,expect,vi} from 'vitest'
import * as THREE from 'three'
import {initAssemblyRenderer} from './assembly_renderer.js'
import {geometryLoads} from './geometry_loads.js'
import {createMockStore} from '../test-helpers/mock_store.js'

it('keeps legacy assembly tracing gated after the CG rebuild until every instance finishes',async()=>{
  const scene=new THREE.Scene(),store=createMockStore({coloringMode:'strand'})
  const instances=['a','b'].map(id=>({id,source:{type:'file',path:`${id}.nadoc`},representation:'vdw',visible:true,transform:{values:new THREE.Matrix4().elements}}))
  const data={design:{helices:[],strands:[],crossovers:[]},nucleotides:[],helix_axes:{}}
  const releases={}
  const api={getAssemblyGeometry:vi.fn(async()=>({instances:Object.fromEntries(instances.map(i=>[i.id,data]))})),
    getInstanceGeometry:vi.fn(async()=>data),
    getInstanceAtomisticGeometry:vi.fn(id=>new Promise(resolve=>{releases[id]=resolve}))}
  const renderer=initAssemblyRenderer(scene,store,api)
  try{
    await renderer.rebuild({instances})
    expect(api.getInstanceAtomisticGeometry).toHaveBeenCalledTimes(2)
    expect(geometryLoads.getState().busy).toBe(true)
    releases.a({atoms:[],bonds:[]})
    await new Promise(r=>setTimeout(r,0))
    expect(geometryLoads.getState().busy).toBe(true)
    renderer.dispose()
    expect(geometryLoads.getState().busy).toBe(false)
  }finally{for(const done of Object.values(releases))done({atoms:[],bonds:[]});await new Promise(r=>setTimeout(r,0));renderer.dispose()}
})
