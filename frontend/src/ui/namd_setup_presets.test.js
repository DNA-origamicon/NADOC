import {it,expect,vi,afterEach} from 'vitest'
import {presetControls,capturePresetControls,applyPresetControls,initNamdSetupPresets} from './namd_setup_presets.js'
afterEach(()=>document.body.replaceChildren())
function mount(){document.body.innerHTML=`<div id="root"><input id="above" value="secret"><section id="md-setup-presets"><select></select><button data-create-preset>Create</button><button data-overwrite-preset>Overwrite</button><button data-delete-preset>Delete</button><form hidden><input name="preset_name"><button type="submit">Save</button><button data-cancel-preset>Cancel</button></form><p role="status"></p></section><input id="charge" type="number" step="any" value="-.02"><input id="md-jobs-display-toggle" type="radio" name="md-viz"><input id="password" type="password"><select id="scope"><option value="all">All</option><option value="local">Local</option></select></div>`;return {root:document.getElementById('root'),host:document.getElementById('md-setup-presets')}}
it('captures all eligible settings and restores values without execution, credentials or fields above the preset',()=>{
 const {root,host}=mount(),fields=presetControls(root,host),data=capturePresetControls(fields)
 expect(Object.keys(data)).toEqual(['charge','scope'])
 document.getElementById('charge').value='-.1';document.getElementById('scope').value='local'
 applyPresetControls(fields,data)
 expect(document.getElementById('charge').value).toBe('-.02');expect(document.getElementById('scope').value).toBe('all')
})
it('creates, selects across designs, overwrites and deletes without deleting current settings',async()=>{
 const {root,host}=mount();let records=[],design={id:'a'}
 const api={listNamdSetupPresets:vi.fn(async()=>records),createNamdSetupPreset:vi.fn(async body=>{const r={...body,id:'one',revision:1};records=[r];return r}),overwriteNamdSetupPreset:vi.fn(async(id,body)=>{const r={...body,id,revision:2};records=[r];return r}),deleteNamdSetupPreset:vi.fn(async()=>{records=[]})}
 const peg={capture:()=>({enabled:true,spec:{repeat_units:40}}),apply:vi.fn(async()=>{})},panel={captureSetupSelections:()=>({anchors:[{helix:1}]}),applySetupSelections:vi.fn(()=> 'Reselect anchors.')}
 const ui=initNamdSetupPresets({api,peg,panel,root,host,store:{getState:()=>({currentDesign:design}),subscribe:()=>()=>{}}})
 await vi.waitFor(()=>expect(api.listNamdSetupPresets).toHaveBeenCalled())
 host.querySelector('[data-create-preset]').click();host.querySelector('input').value='Brush';host.querySelector('form').dispatchEvent(new Event('submit',{cancelable:true}))
 await vi.waitFor(()=>expect(host.querySelector('select').value).toBe('one'))
 design={id:'b'};document.getElementById('charge').value='-.1'
 host.querySelector('select').dispatchEvent(new Event('change'))
 await vi.waitFor(()=>expect(peg.apply).toHaveBeenCalled())
 expect(document.getElementById('charge').value).toBe('-.02');expect(panel.applySetupSelections).toHaveBeenCalledWith({anchors:[{helix:1}]},false)
 await vi.waitFor(()=>expect(host.querySelector('[data-overwrite-preset]').disabled).toBe(false))
 document.getElementById('charge').value='-.05';host.querySelector('[data-overwrite-preset]').click()
 await vi.waitFor(()=>expect(records[0].revision,host.querySelector('[role=status]').textContent).toBe(2))
 await vi.waitFor(()=>expect(host.querySelector('[data-delete-preset]').disabled).toBe(false));host.querySelector('[data-delete-preset]').click()
 await vi.waitFor(()=>expect(records).toEqual([]));expect(document.getElementById('charge').value).toBe('-.05');ui.dispose()
})
