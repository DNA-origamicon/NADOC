import {it,expect,vi,afterEach} from 'vitest'
import {initNamdSurfaceCard} from './namd_surface_card.js'
let ui
const setup=()=>{
 document.body.innerHTML='<input type="checkbox" id="md-hard-surface-enable"><input type="checkbox" id="md-surface-enable"><input type="checkbox" id="md-screening-enable"><div id="md-surface-ready"></div>'
 ui=initNamdSurfaceCard();return ui
}
afterEach(()=>{ui?.dispose();document.body.replaceChildren()})
it('only an explicit selection of a surface job renders; setup and automatic selection do not',()=>{
 const events=[],listen=e=>events.push(e.detail)
 window.addEventListener('nadoc:graphene-nanopore-preview',listen)
 const card=setup(), job={job_id:'surface'},prep={graphene_nanopore:true,graphene_pore_diameter_nm:0,graphene_surface_axis:'+z',graphene_surface_offset_nm:2}
 document.querySelector('#md-hard-surface-enable').click()
 expect(events.at(-1).enabled).toBe(false)
 card.select(job,prep);expect(events.at(-1).enabled).toBe(false)
 card.select(job,prep,true);expect(events.at(-1)).toMatchObject({enabled:true,poreDiameterNm:0,surface:{dir:[0,0,-1],positionNm:2}})
 document.querySelector('#md-surface-enable').click()
 expect(events.at(-1).poreDiameterNm).toBe(0)
 card.select({job_id:'plain'},{},true);expect(events.at(-1).enabled).toBe(false)
 card.select(job,prep,true);card.clear();expect(events.at(-1).enabled).toBe(false)
 window.removeEventListener('nadoc:graphene-nanopore-preview',listen)
})
it('groups dependent options without mixing closed charge and open nanopore',()=>{
 const card=setup(),hard=document.querySelector('#md-hard-surface-enable'),pore=document.querySelector('#md-surface-enable'),charge=document.querySelector('#md-screening-enable')
 charge.click();expect(hard.checked).toBe(true);expect(card.poreDiameter(3)).toBe(0)
 pore.click();expect(charge.checked).toBe(false);expect(card.poreDiameter(3)).toBe(3)
 hard.click();expect(pore.checked).toBe(false);expect(card.enabled()).toBe(false)
 card.restore({graphene_nanopore:true,graphene_pore_diameter_nm:0});expect(hard.checked).toBe(true);expect(pore.checked).toBe(false)
})
