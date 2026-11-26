import {it,expect} from 'vitest'
import {traceDenoiseTile,TRACE_DENOISE_HALO} from './trace_denoise.js'

it('pads interior export tiles with real neighbours and crops exactly to the core',()=>{
  expect(traceDenoiseTile(1,1,2500,2500,834,834,TRACE_DENOISE_HALO)).toEqual({
    x:828,y:828,width:846,height:846,cropX:6,cropY:6,coreWidth:834,coreHeight:834,left:834,top:834,
  })
})
it('covers odd-sized output exactly without padding beyond image boundaries',()=>{
  const w=2051,h=1027,tw=684,th=514,visited=new Uint8Array(w*h)
  for(let y=0;y<2;y++)for(let x=0;x<3;x++){
    const t=traceDenoiseTile(x,y,w,h,tw,th,6)
    expect(t.x).toBeGreaterThanOrEqual(0);expect(t.y).toBeGreaterThanOrEqual(0)
    expect(t.x+t.width).toBeLessThanOrEqual(w);expect(t.y+t.height).toBeLessThanOrEqual(h)
    expect(t.x+t.cropX).toBe(t.left);expect(t.y+t.cropY).toBe(t.top)
    for(let j=t.top;j<t.top+t.coreHeight;j++)for(let i=t.left;i<t.left+t.coreWidth;i++)visited[j*w+i]++
  }
  expect(visited.every(n=>n===1)).toBe(true)
  expect(traceDenoiseTile(2,1,w,h,tw,th,0)).toMatchObject({width:683,height:513,cropX:0,cropY:0})
})
