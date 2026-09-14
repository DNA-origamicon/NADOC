import './namd_setup_presets.css'

const OMIT = /^(md-jobs-(?:viz-off|display-toggle|flex-toggle|photoproduct-toggle|occupancy-toggle|traj-toggle|traj-slider|show-all)|md-ion-(?:paths-toggle|vector-field-toggle))$/
/** Only editable settings below the preset selector; never job ownership or actions. */
export function presetControls(root, marker) {
 return [...root.querySelectorAll('input[id],select[id],textarea[id]')].filter(el=>
  !!(marker.compareDocumentPosition(el)&Node.DOCUMENT_POSITION_FOLLOWING) &&
  !el.closest('#md-setup-presets,#namd-peg-surfaces,#md-jobs-list,#md-jobs-detail') &&
  el.id!=='md-peg-enable' && !OMIT.test(el.id) && !['password','file','hidden','submit','button'].includes(el.type) &&
  el.name!=='md-viz' && !el.readOnly)
}
export function capturePresetControls(elements) {
 const result={}
 for(const el of elements){
  if(!el.disabled && !el.checkValidity())throw Error(`Correct ${el.labels?.[0]?.textContent?.trim() || el.id} before saving.`)
  result[el.id]={type:el.type,value:el.value,...(['checkbox','radio'].includes(el.type)?{checked:el.checked}:{})}
 }
 return result
}
export function applyPresetControls(elements,values={}) {
 const changed=[]
 for(const el of elements){const state=values[el.id];if(!state || state.type!==el.type)continue
  if(el.tagName==='SELECT' && ![...el.options].some(o=>o.value===state.value))continue
  if(el.type!=='radio')el.value=state.value
  if('checked' in state)el.checked=!!state.checked
  changed.push(el)
 }
 // Set all values before notifying controllers so dependent cards see one coherent setup.
 for(const el of changed){if(el.type==='radio' && !el.checked)continue;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))}
}
export function initNamdSetupPresets({api,store,peg,panel,host=document.getElementById('md-setup-presets'),root=document.getElementById('md-jobs-panel-body')}={}) {
 if(!host || !root)return null
 const select=host.querySelector('select'),create=host.querySelector('[data-create-preset]'),overwrite=host.querySelector('[data-overwrite-preset]'),remove=host.querySelector('[data-delete-preset]'),form=host.querySelector('form'),status=host.querySelector('[role=status]')
 let records=[],selected=null,busy=false,applying=false,designId=store?.getState()?.currentDesign?.id,disposed=false
 const controls=()=>presetControls(root,host)
 const capture=()=>({schema:'nadoc.namd_setup.v1',controls:capturePresetControls(controls()),peg:peg?.capture(),selections:panel?.captureSetupSelections?.(),source_design_id:store?.getState()?.currentDesign?.id || null})
 function paint(){
  select.replaceChildren(new Option('Custom settings',''))
  for(const r of records)select.add(new Option(r.name,r.id))
  select.value=selected?.id || '';select.disabled=create.disabled=busy;overwrite.disabled=remove.disabled=busy || !selected
  overwrite.title=selected?`Replace ${selected.name} with all current settings below`:'Select a preset to overwrite'
  remove.title=selected?`Delete preset ${selected.name}`:'Select a preset to delete'
 }
 async function refresh(){records=await api.listNamdSetupPresets();if(!Array.isArray(records))throw Error('Could not load setup presets.');if(selected)selected=records.find(r=>r.id===selected.id) || null;paint()}
 async function action(fn){if(busy)return;busy=true;paint();try{await fn()}catch(e){status.textContent=e.message}finally{busy=false;paint()}}
 select.addEventListener('change',()=>{const choice=select.value;return action(async()=>{
  selected=records.find(r=>r.id===choice) || null
  if(!selected){status.textContent='Custom settings';return}
  const preset=selected,id=store?.getState()?.currentDesign?.id
  applying=true
  try{
   applyPresetControls(controls(),preset.settings.controls)
   await peg?.apply(preset.settings.peg || null)
   if(id!==store?.getState()?.currentDesign?.id)throw Error('Document changed while applying the preset. Select it again.')
   const sameDesign=!!id && preset.settings.source_design_id===id
   const warning=panel?.applySetupSelections?.(preset.settings.selections || {},sameDesign)
   status.textContent=`Applied ${preset.name} · revision ${preset.revision}.${warning?' '+warning:''}`
  }finally{applying=false}
 })})
 create.addEventListener('click',()=>{form.hidden=false;form.elements.preset_name.value='';form.elements.preset_name.focus()})
 host.querySelector('[data-cancel-preset]').addEventListener('click',()=>{form.hidden=true})
 form.addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  const name=form.elements.preset_name.value.trim();if(!name)throw Error('Enter a preset name.')
  const record=await api.createNamdSetupPreset({name,settings:capture()});if(!record)throw Error('Could not save preset.')
  selected=record;await refresh();form.hidden=true;status.textContent=`Created ${record.name}.`
 })})
 overwrite.addEventListener('click',()=>action(async()=>{
  const record=await api.overwriteNamdSetupPreset(selected.id,{name:selected.name,revision:selected.revision,settings:capture()})
  if(!record)throw Error('Could not overwrite preset.');selected=record;await refresh();status.textContent=`Overwrote ${record.name} · revision ${record.revision}.`
 }))
 remove.addEventListener('click',()=>action(async()=>{
  const name=selected.name;await api.deleteNamdSetupPreset(selected.id,selected.revision);selected=null;await refresh();status.textContent=`Deleted ${name}. Current settings retained.`
 }))
 const edited=event=>{if(!applying && selected && !host.contains(event.target))status.textContent=`Modified from ${selected.name}. Overwrite to update it, or Create a new preset.`}
 root.addEventListener('change',edited);root.addEventListener('input',edited)
 const unsubscribe=store?.subscribe(()=>{const id=store.getState()?.currentDesign?.id;if(id===designId)return;designId=id;selected=null;form.hidden=true;status.textContent='Select a preset to reuse its settings for this design.';paint()})
 refresh().catch(e=>{if(!disposed)status.textContent=e.message})
 return {capture,refresh,dispose(){disposed=true;unsubscribe?.();root.removeEventListener('change',edited);root.removeEventListener('input',edited)}}
}
