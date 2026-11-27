import {it,expect} from 'vitest'
import * as THREE from 'three'
import {reuseTraceGeometry,sameTraceArray} from './path_trace_reuse.js'
it('refits moved vertices while retaining the BVH index order and refuses changed connectivity',()=>{
  const a=new THREE.BoxGeometry(),b=a.clone(),original=a.index.array.slice()
  const reordered=a.index.array.reverse().slice()
  b.translate(3,0,0)
  expect(reuseTraceGeometry(a,b,original)).toEqual({moved:true})
  expect(a.index.array).toEqual(reordered)
  expect(a.attributes.position.array).toEqual(b.attributes.position.array)
  expect(reuseTraceGeometry(a,b,original)).toEqual({moved:false})
  b.index.array[0]=999;expect(reuseTraceGeometry(a,b,original)).toBeNull()
  expect(sameTraceArray(null,original)).toBe(false)
  a.dispose();b.dispose()
})
