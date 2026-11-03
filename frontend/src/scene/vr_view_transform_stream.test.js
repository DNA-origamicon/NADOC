import { it, expect } from 'vitest'
import { encodeTransformUpdate } from './vr_view_transform_stream.js'
function fixture() {
 const instances=new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 2,3,4,1, .2,.3,.4,1])
 const base={schema:5,flags:2048,atlasState:{},batches:[{name:'atoms',vertices:new Float32Array(36),instances}],triangles:new Float32Array(),lines:new Float32Array(),sprites:new Float32Array()}
 const next={...base,schema:6,batches:[{...base.batches[0],instances:instances.slice()}]}
 return {base,next}
}
it('sends exact translation values against a fixed full snapshot, independent of intervening frames', async()=>{
 const {base,next}=fixture();next.batches[0].instances[12]=42
 const blob=encodeTransformUpdate(next,base,7,9,2), buffer=await blob.arrayBuffer()
 expect([...new Uint32Array(buffer,8,11)]).toEqual([7,9,2048,0,0,0,0,0,1,2,7])
 expect([...new Uint32Array(buffer,52,2)]).toEqual([1,3])
 expect([...new Float32Array(buffer,60)]).toEqual([42,3,4])
 next.batches[0].instances[12]=2
 expect([...new Float32Array(await encodeTransformUpdate(next,base,7,10).arrayBuffer(),60)]).toEqual([2,3,4])
})
it('preserves every affine component for rotating/scaling bonds without decomposition', async()=>{
 const {base,next}=fixture();next.batches[0].instances[4]=.125;next.batches[0].instances[14]=-0
 const buf=await encodeTransformUpdate(next,base,7,10).arrayBuffer()
 expect([...new Uint32Array(buf,52,2)]).toEqual([1,12])
 expect([...new Float32Array(buf,60)]).toEqual([1,0,0,.125,1,0,0,0,1,2,3,-0])
})
it('falls back for geometry, atlas, layout, colors, visibility, and non-affine matrices',()=>{
 for(const change of [n=>n.schema=5,n=>n.flags=0,n=>n.atlasState={},n=>n.batches=[],n=>n.batches[0].name='bonds',n=>n.batches[0].vertices=new Float32Array(36).fill(1),n=>n.batches[0].instances[16]=1,n=>n.batches[0].instances[19]=0,n=>n.batches[0].instances[3]=1]){
  const {base,next}=fixture();change(next);expect(encodeTransformUpdate(next,base,7,10)).toBeNull()
 }
})

it('reuses byte-identical templates even when shared materials replace cache entries',()=>{
 const {base,next}=fixture();next.batches[0].vertices=base.batches[0].vertices.slice()
 expect(encodeTransformUpdate(next,base,7,8)).not.toBeNull()
 next.batches[0].vertices[0]=-0
 expect(encodeTransformUpdate(next,base,7,8)).toBeNull()
})
