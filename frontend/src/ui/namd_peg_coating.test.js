import {it,expect,vi,afterEach} from 'vitest'
import {initNamdPegCoating} from './namd_peg_coating.js'
let ui
afterEach(()=>{ui?.dispose();document.body.replaceChildren()})
function setup(){
 document.body.innerHTML='<input id="md-peg-enable" type="checkbox"><div id="namd-peg-surfaces"><form></form><input type="checkbox" data-view-peg checked><button data-review-coating>Review</button><p role="status"></p></div>'
 let listener;const state={currentDesign:{id:'a',metadata:{}}},api={updateMetadata:vi.fn(async()=>{}),reviewNamdPegSurface:vi.fn(async()=>({summary:{chains:20}}))}
 ui=initNamdPegCoating({api,store:{getState:()=>state,subscribe:fn=>{listener=fn;return ()=>{}}}})
 return {api,change:d=>{state.currentDesign=d;listener()}}
}
it('edits and persists inline coating settings without creating a surface draft or popup',async()=>{
 const {api}=setup();document.getElementById('md-peg-enable').click()
 const units=document.getElementById('md-peg-repeat_units');units.value='80';units.dispatchEvent(new Event('input',{bubbles:true}))
 await ui.flush();expect(api.updateMetadata).toHaveBeenLastCalledWith(expect.objectContaining({namd_peg_coating:expect.objectContaining({enabled:true,spec:expect.objectContaining({repeat_units:80})})}))
 document.querySelector('[data-review-coating]').click();await vi.waitFor(()=>expect(api.reviewNamdPegSurface).toHaveBeenCalled())
 expect(document.querySelector('[role=dialog]')).toBeNull()
 document.getElementById('md-peg-enable').click();await ui.flush();expect(ui.capture().enabled).toBe(false);expect(ui.capture().spec.repeat_units).toBe(80)
})
it('restores legacy coating intent and ignores pending writes after switching documents',async()=>{
 const {api,change}=setup();document.getElementById('md-peg-enable').click()
 change({id:'b',metadata:{namd_peg_coating:{spec:{repeat_units:64}},namd_peg_visible:false}})
 await ui.flush();expect(api.updateMetadata).not.toHaveBeenCalled()
 expect(ui.capture()).toMatchObject({enabled:true,visible:false,spec:{repeat_units:64}})
})

it('preserves both representation parameter sets in a reusable coating snapshot',async()=>{
 setup();document.getElementById('md-peg-repeat_units').value='80'
 const rep=document.getElementById('md-peg-representation');rep.value='coarse_grained';rep.dispatchEvent(new Event('change',{bubbles:true}))
 document.getElementById('md-peg-segments').value='12'
 expect(ui.capture().spec).toMatchObject({repeat_units:80,segments:12,representation:'coarse_grained'})
})
