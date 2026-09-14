import {it,expect,vi} from 'vitest'
import {initNamdPegAttachment} from './namd_peg_attachment.js'
it('persists attachment/removal and visibility without deleting the library record',async()=>{
 document.body.innerHTML='<div id="host"><button data-new-surface></button><p role="status"></p></div>'
 let listener
 const state={currentDesign:{id:'a',metadata:{}}}
 const store={getState:()=>state,subscribe:fn=>{listener=fn;return()=>{}}}
 const api={updateMetadata:vi.fn(async fields=>{Object.assign(state.currentDesign.metadata,fields);listener()})}
 const ui=initNamdPegAttachment({host:document.getElementById('host'),api,store})
 const record={id:'saved',spec:{name:'coat'},preview:{graft_sites_nm:[[1,2,3]]}}
 await ui.set(record,'a')
 expect(document.querySelector('[data-new-surface]').textContent).toBe('Edit PEG coating')
 document.querySelector('[data-view-peg]').click()
 await vi.waitFor(()=>expect(state.currentDesign.metadata.namd_peg_visible).toBe(false))
 await vi.waitFor(()=>expect(document.querySelector('[data-remove-coating]').disabled).toBe(false))
 document.querySelector('[data-remove-coating]').click()
 await vi.waitFor(()=>expect(state.currentDesign.metadata.namd_peg_coating).toBeNull())
 expect(document.querySelector('[data-new-surface]').textContent).toBe('Add PEG coating')
 expect(record.id).toBe('saved')
 state.currentDesign={id:'b',metadata:{namd_peg_coating:record}};listener()
 expect(document.querySelector('[data-new-surface]').textContent).toBe('Edit PEG coating')
 await expect(ui.set(record,'a')).rejects.toThrow('Document changed')
 ui.dispose()
})
