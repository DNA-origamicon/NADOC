import {it,expect} from 'vitest'
import {readNativeImage} from './path_trace_native_image.js'
it('counts received image bytes and preserves pixels',async()=>{
  const progress=[],body=new ReadableStream({start(c){c.enqueue(new Uint8Array([1,2]));c.enqueue(new Uint8Array([3,4]));c.close()}})
  const result=await readNativeImage(new Response(body),4,undefined,p=>progress.push(p.fraction))
  expect([...new Uint8Array(result)]).toEqual([1,2,3,4]);expect(progress).toEqual([0,.5,1])
})
it('rejects truncated frames',async()=>{
  await expect(readNativeImage(new Response(new Uint8Array([1])),4)).rejects.toThrow('incomplete')
})
