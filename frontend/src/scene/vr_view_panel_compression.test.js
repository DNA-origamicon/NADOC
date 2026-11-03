import {it,expect} from 'vitest'
import {compressVRPanel} from './vr_view_panel_compression.js'
function decode(bytes){
 const runs=new Uint32Array(bytes.buffer,bytes.byteOffset,bytes.byteLength/4),pixels=[]
 for(let i=0;i<runs.length;i+=2)for(let n=0;n<runs[i];n++)pixels.push(runs[i+1])
 return new Uint8Array(new Uint32Array(pixels).buffer)
}
it('preserves exact antialiasing pixels and invalidates cached runs',()=>{
 const pixels=new Uint8Array(1024).fill(127),atlasState={panelKey:'first'}
 pixels.set([10,20,30,40],128);pixels.set([41,31,21,11],132)
 const view={schema:8,pixels,atlasState},packed=compressVRPanel(view)
 expect(packed.schema).toBe(10);expect(packed.pixels.length).toBeLessThan(pixels.length/10)
 expect(decode(packed.pixels)).toEqual(pixels)
 expect(compressVRPanel({...view,schema:9}).pixels).toBe(packed.pixels)
 pixels[0]=42;atlasState.panelKey='second'
 expect(decode(compressVRPanel(view).pixels)).toEqual(pixels)
 const full={...view,schema:5};expect(compressVRPanel(full)).toBe(full)
})
it('retains raw pixels when run packing would enlarge the packet',()=>{
 const pixels=new Uint8Array(new Uint32Array(Array.from({length:64},(_,i)=>i)).buffer)
 const view={schema:8,pixels};expect(compressVRPanel(view)).toBe(view)
})
