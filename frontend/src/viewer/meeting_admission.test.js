import {it,expect,vi,afterEach} from 'vitest'
import {mountMeetingAdmission} from './meeting_admission.js'
afterEach(()=>{document.body.innerHTML='';vi.restoreAllMocks()})
function setup(state='waiting') {
 document.body.innerHTML='<main></main>';Object.defineProperty(document,'hidden',{configurable:true,value:false})
 let tick,reply={admission:{state,position:2,serverTime:1000,offerUntil:31000}},resolve
 const request=vi.fn(async()=>({ok:true,json:async()=>reply})),onActive=vi.fn(),onSuspend=vi.fn(),onRejoin=vi.fn()
 const ui=mountMeetingAdmission({details:reply,base:'/meeting/x',fetch:request,onActive,onSuspend,onRejoin,onEnded:vi.fn(),setInterval:fn=>{tick=fn;return 1},clearInterval:vi.fn()})
 return {ui,request,onActive,onSuspend,onRejoin,tick:()=>tick(),reply:value=>reply={admission:value},el:s=>document.querySelector(s)}
}
it('waiting downloads nothing, offers require acceptance, rotation activates directly, released guests explicitly rejoin',async()=>{
 const x=setup();expect(x.onActive).not.toHaveBeenCalled();expect(x.el('[data-message]').textContent).toContain('number 2')
 x.reply({state:'offered',offerUntil:31000,serverTime:1000});x.tick();await vi.waitFor(()=>expect(x.el('[data-accept]').hidden).toBe(false));expect(x.onActive).not.toHaveBeenCalled()
 x.reply({state:'active'});x.el('[data-accept]').click();await vi.waitFor(()=>expect(x.onActive).toHaveBeenCalledOnce());expect(JSON.parse(x.request.mock.calls.at(-1)[1].body).action).toBe('accept')
 x.reply({state:'released',reason:'rotated'});x.tick();await vi.waitFor(()=>expect(x.onSuspend).toHaveBeenCalledOnce());expect(x.el('[data-message]').textContent).toContain('welcoming new guests')
 x.el('[data-rejoin]').click();expect(x.onRejoin).toHaveBeenCalledOnce();x.ui.dispose()
})
it('background suspends immediately, visibility reports separately, explicit leave and still-watching work',async()=>{
 const x=setup('active');await vi.waitFor(()=>expect(x.onActive).toHaveBeenCalledOnce())
 Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));expect(x.onSuspend).toHaveBeenCalledOnce()
 await vi.waitFor(()=>expect(x.request).toHaveBeenCalled());expect(JSON.parse(x.request.mock.calls[0][1].body).visible).toBe(false)
 Object.defineProperty(document,'hidden',{configurable:true,value:false});x.reply({state:'active',promptUntil:31000});document.dispatchEvent(new Event('visibilitychange'))
 await vi.waitFor(()=>expect(x.el('[data-stay]').hidden).toBe(false));x.el('[data-stay]').click();await vi.waitFor(()=>expect(JSON.parse(x.request.mock.calls.at(-1)[1].body).active).toBe(true))
 x.reply({state:'released',reason:'left'});x.el('[data-leave]').click();await vi.waitFor(()=>expect(x.el('[data-title]').textContent).toBe('Your place was released'));x.ui.dispose()
})
