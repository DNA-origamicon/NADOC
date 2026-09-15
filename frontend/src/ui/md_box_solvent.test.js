import {it,expect,vi,afterEach} from 'vitest'
import {readFileSync} from 'node:fs'
import {initBoxSolvent,solventNumbers} from './md_box_solvent.js'
let ui
afterEach(()=>{ui?.dispose();document.body.replaceChildren()})
it('estimates bulk salt counts from liquid volume, not a slab vacuum cell',()=>{
 expect(solventNumbers([10,10,10],300,0)).toMatchObject({na:181,mg:0,cl:181,volume_nm3:1000})
 expect(solventNumbers([10,10,10],0,12.5)).toMatchObject({na:0,mg:8,cl:16})
})
it('persists explicit preparation, renders live details and restores without salt overrides',async()=>{
 const source=new DOMParser().parseFromString(readFileSync('index.html','utf8'),'text/html')
 document.body.append(source.querySelector('#md-box-solvent-body'),source.querySelector('#md-surface-body'))
 const api={fetchProtocolBoxPreview:vi.fn(async p=>({box_preview:{calculated_nm:p.box_size_nm || [12,13,14],selected_nm:p.box_size_nm || [12,13,14]}})),updateMetadata:vi.fn(async()=>({}))}
 const store={getState:()=>({currentDesign:{id:'one',metadata:{}}}),subscribe:()=>()=>{}}
 const events=[],listen=e=>events.push(e.detail);window.addEventListener('nadoc:box-solvent-details',listen)
 ui=initBoxSolvent({api,store})
 const change=(id,value)=>{const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}))}
 change('md-box-sizing','explicit');change('md-box-x','10');change('md-box-y','15');change('md-box-z','20');change('md-box-salt','custom');change('md-box-na','175');change('md-box-mg','0')
 document.getElementById('md-box-view-details').click()
 await vi.waitFor(()=>expect(events.at(-1)).toMatchObject({enabled:true,dimensions:[10,15,20],na:175,mg:0}),{timeout:2000})
 expect(ui.payload()).toMatchObject({box_size_nm:[10,15,20],salt_mode:'custom',ion_conc_mM:175,mg_conc_mM:0})
 await vi.waitFor(()=>expect(api.updateMetadata).toHaveBeenCalled(),{timeout:2000})
 ui.restore({box_size_nm:[8,9,10],salt_mode:'custom',ion_conc_mM:100,mg_conc_mM:2})
 expect(ui.payload()).toMatchObject({box_size_nm:[8,9,10],ion_conc_mM:100,mg_conc_mM:2})
 window.removeEventListener('nadoc:box-solvent-details',listen)
})

it('tracks the latest calculation, reports failures inline and keeps automatic sizes automatic',async()=>{
 const source=new DOMParser().parseFromString(readFileSync('index.html','utf8'),'text/html')
 for(const id of ['md-box-solvent-toggle','md-box-solvent-body','md-surface-body'])document.body.append(source.getElementById(id))
 const requests=[]
 const api={fetchProtocolBoxPreview:vi.fn(()=>new Promise(resolve=>requests.push(resolve))),updateMetadata:vi.fn(async()=>({}))}
 ui=initBoxSolvent({api,store:{getState:()=>({}),subscribe:()=>()=>{}}})
 const spinner=document.getElementById('md-box-loading'),warning=document.getElementById('md-box-warning')
 expect(spinner.hidden).toBe(false)
 await vi.waitFor(()=>expect(requests).toHaveLength(1))
 ui.refresh()
 await vi.waitFor(()=>expect(requests).toHaveLength(2))
 requests[0]({box_preview:{selected_nm:[5,5,5]}})
 await Promise.resolve()
 expect(spinner.hidden).toBe(false)
 requests[1]({warnings:['The geometry could not be fitted.']})
 await vi.waitFor(()=>expect(spinner.hidden).toBe(true))
 expect(warning.hidden).toBe(false)
 warning.click()
 expect(document.getElementById('md-box-solvent-body').style.display).toBe('')
 expect(document.getElementById('md-box-warnings').textContent).toContain('could not be fitted')
 ui.refresh()
 await vi.waitFor(()=>expect(requests).toHaveLength(3))
 requests[2]({box_preview:{selected_nm:[12,13,14]}})
 await vi.waitFor(()=>expect(spinner.hidden).toBe(true))
 expect(warning.hidden).toBe(true)
 expect(ui.payload().box_size_nm).toBeNull()
 expect(document.getElementById('md-box-x').value).toBe('12.000')
 document.getElementById('md-hard-surface-enable').checked=true
 document.getElementById('md-box-sizing').dispatchEvent(new Event('change',{bubbles:true}))
 expect(ui.payload()).toMatchObject({box_mode:'bbox',box_size_nm:null,padding_nm:2})
 document.getElementById('md-box-sizing').value='rotation'
 document.getElementById('md-box-sizing').dispatchEvent(new Event('change',{bubbles:true}))
 expect(ui.payload().box_mode).toBe('rotation')
 ui.setJobWarnings([{key:'job',name:'cube',message:'Box X needs 20 nm'}])
 expect(warning.hidden).toBe(false)
})
