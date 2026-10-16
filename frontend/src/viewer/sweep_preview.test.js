import {it,expect,vi} from 'vitest'
import * as THREE from 'three'
import {validateSweepPreview} from './sweep_preview_protocol.js'
import {createSweepPreview} from './sweep_preview.js'
import {initSweepPreviewPublisher} from './sweep_preview_publisher.js'
const packet=()=>({trackingToSource:new THREE.Matrix4().makeScale(10,10,10).toArray(),model:new THREE.Matrix4().toArray(),radius:.024,selected:1,
  nodes:[[0,0,0],[0,0,2]],frames:[[1,0,0,0,1,0],[1,0,0,0,1,0]],path:[[0,0,0],[0,0,1],[0,0,2]],outline:[[0,0],[1,0],[0,1]],cells:[[0,0]]})
it('bounds preview geometry and rejects malformed frames, transforms and indexes',()=>{
 expect(validateSweepPreview(packet())).toEqual(packet())
 for(const change of [{nodes:Array(257).fill([0,0,0])},{path:[[NaN,0,0]]},{selected:2},{frames:[[0,0,0,0,0,0]]},{model:Array(16).fill(0)}])expect(()=>validateSweepPreview({...packet(),...change})).toThrow()
})
it('renders independent path, sections and double-size nodes; expires and clears without changing the model',()=>{
 let now=0;const scene=new THREE.Scene(),p=createSweepPreview({scene,now:()=>now}),data=packet()
 p.receive({preview:{data,expiresAt:3000},serverTime:0});p.frame();expect(p.root.visible).toBe(true)
 const [lines,nodes]=p.root.children
 expect(lines.geometry.getAttribute('position').count).toBeGreaterThan(10);expect(nodes.count).toBe(2)
 const matrix=new THREE.Matrix4();nodes.getMatrixAt(1,matrix);expect(matrix.elements[0]).toBeCloseTo(.024);expect(matrix.elements[14]).toBe(2)
 const buffer=lines.geometry.getAttribute('position');p.receive({preview:{data,expiresAt:4000},serverTime:1000});expect(lines.geometry.getAttribute('position')).toBe(buffer)
 now=3001;p.frame();expect(p.root.visible).toBe(false)
 p.receive({preview:null});expect(nodes.count).toBe(0);p.dispose();expect(scene.children).toHaveLength(0)
})
it('sends changed geometry only, renews via small heartbeats, clears on cancel, republishes after revision changes',async()=>{
 let now=0,preview=packet(),room={id:'room',revision:'one'}
 const publish=vi.fn(async()=>{}),request=vi.fn(async()=>({ok:true,json:async()=>({preview})}))
 const p=initSweepPreviewPublisher({getRoom:()=>room,available:()=>true,publish,request,now:()=>now,setInterval:()=>1,clearInterval:()=>{}})
 await p.tick();expect(publish.mock.calls[0][1].preview).toEqual(preview)
 now=100;await p.tick();expect(publish).toHaveBeenCalledTimes(1)
 now=1001;await p.tick();expect(publish.mock.calls.at(-1)[1]).toEqual({revision:'one',keep:true})
 room={...room,revision:'two'};await p.tick();expect(publish.mock.calls.at(-1)[1].preview).toEqual(preview)
 preview=null;await p.tick();expect(publish.mock.calls.at(-1)[1]).toEqual({revision:'two',preview:null})
 await p.tick();expect(publish).toHaveBeenCalledTimes(4);p.dispose()
})

it('coalesces large drafts to the newest geometry within a bandwidth budget and clears immediately',async()=>{
 let now=0,preview={...packet(),path:Array.from({length:512},(_,i)=>[i+.123456789,i+.987654321,i+.135792468])}
 const publish=vi.fn(async()=>{}),p=initSweepPreviewPublisher({getRoom:()=>({id:'room',revision:'one'}),available:()=>true,publish,
  request:async()=>({ok:true,json:async()=>({preview})}),now:()=>now,setInterval:()=>1,clearInterval:()=>{}})
 await p.tick();expect(publish).toHaveBeenCalledTimes(1)
 now=100;preview={...preview,selected:0};await p.tick();expect(publish).toHaveBeenCalledTimes(1)
 now=200;preview={...preview,nodes:[[1,0,0],[0,0,2]]};await p.tick();expect(publish).toHaveBeenCalledTimes(1)
 now=1000;await p.tick();expect(publish).toHaveBeenCalledTimes(2);expect(publish.mock.calls.at(-1)[1].preview.nodes[0]).toEqual([1,0,0])
 now=1001;preview=null;await p.tick();expect(publish.mock.calls.at(-1)[1].preview).toBeNull();p.dispose()
})
