import {it, expect} from 'vitest'
import {checkTraceGeometry, checkTraceBVH, checkWebGPUStorage, traceDeviceLimits} from './path_trace_limits.js'

it('admits more than three million triangles when their textures fit the device', () => {
  expect(()=>checkTraceGeometry({vertices:4000000,triangles:8000000},4096)).not.toThrow()
  expect(()=>checkTraceGeometry({vertices:4000000,triangles:8000000},2048)).toThrow(/triangle indices.*2048/)
  expect(()=>checkTraceGeometry({vertices:0x100000001,triangles:1})).toThrow(/32-bit/)
})
it('uses the built BVH size rather than rejecting a pessimistic node-count estimate', () => {
  expect(()=>checkTraceBVH({_roots:[{byteLength:1024*32}]},64)).not.toThrow()
  expect(()=>checkTraceBVH({_roots:[{byteLength:4096*32}]},64)).toThrow(/acceleration data/)
})
it('checks actual packed storage against the requested WebGPU device limits', () => {
  const storage={attributes:{value:{array:{byteLength:200*1048576}}}}
  expect(()=>checkWebGPUStorage(storage,{maxBufferSize:1024*1048576,maxStorageBufferBindingSize:256*1048576})).not.toThrow()
  expect(()=>checkWebGPUStorage(storage,{maxBufferSize:1024*1048576,maxStorageBufferBindingSize:128*1048576})).toThrow(/200.0 MiB.*128.0 MiB/)
  expect(traceDeviceLimits({maxBufferSize:1024,maxStorageBufferBindingSize:512,maxTextureDimension2D:8192,maxTextureArrayLayers:256})).toMatchObject({maxStorageBufferBindingSize:512,maxBufferSize:1024})
})
