import { it,expect,vi } from 'vitest'
import { resizeInsetRect,initZoomInsetResize } from './zoom_volume_resize.js'
const rect={left:200,top:100,right:480,bottom:406,width:280,height:306}
const bounds={left:8,top:8,right:900,bottom:700}
it('resizes edges and corners independently while anchoring the opposite edge',()=>{
 expect(resizeInsetRect(rect,'se',90,50,bounds)).toEqual({left:200,top:100,right:570,bottom:456,width:370,height:356})
 expect(resizeInsetRect(rect,'nw',-40,-20,bounds)).toEqual({left:160,top:80,right:480,bottom:406,width:320,height:326})
 expect(resizeInsetRect(rect,'e',70,999,bounds).height).toBe(306)
 expect(resizeInsetRect(rect,'s',999,70,bounds).width).toBe(280)
 for(const edge of ['n','s','e','w','ne','nw','se','sw']){
  const r=resizeInsetRect(rect,edge,-999,999,bounds)
  expect(r.width).toBeGreaterThanOrEqual(160);expect(r.height).toBeGreaterThanOrEqual(120)
  expect(r.left).toBeGreaterThanOrEqual(8);expect(r.bottom).toBeLessThanOrEqual(700)
 }
})
it('commits once on pointer release, restores on cancellation, and supports keyboard resize',()=>{
 const host=document.createElement('div');host.getBoundingClientRect=()=>rect
 const change=vi.fn(),commit=vi.fn(),resize=initZoomInsetResize({host,getBounds:()=>bounds,onResize:change,onCommit:commit})
 const handle=host.querySelector('[data-resize-edge=se]')
 const event=(type,x,y)=>{const e=new MouseEvent(type,{clientX:x,clientY:y,bubbles:true});Object.defineProperty(e,'pointerId',{value:1});handle.dispatchEvent(e)}
 event('pointerdown',480,406);event('pointermove',550,450)
 expect(change).toHaveBeenLastCalledWith(expect.objectContaining({width:350,height:350}));expect(commit).not.toHaveBeenCalled()
 event('pointerup',550,450);expect(commit).toHaveBeenCalledTimes(1)
 event('pointerdown',480,406);event('pointermove',600,600);event('pointercancel',600,600)
 expect(change).toHaveBeenLastCalledWith(rect)
 handle.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight'}))
 expect(change).toHaveBeenLastCalledWith(expect.objectContaining({width:290,height:306}))
 resize.dispose();expect(host.children).toHaveLength(0)
})
