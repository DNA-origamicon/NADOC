import {NAMD_PEG_DEFAULTS,namdPegFormSpec,namdPegEstimate} from './namd_peg_surface_model.js'

const FIELDS = [
 ['Patch shape','shape',[['square','Square'],['circle','Circle']]],
 ['Patch width / diameter (nm)','size_nm',2,1000],
 ['Graft density (chains/nm²)','density_per_nm2',.000001,10],
 ['Layout seed','seed',0,4294967295,1],
 ['PEG representation','representation',[['atomistic','Atomistic PEG'],['coarse_grained','Coarse-grained PEG']]],
 ['Ethylene-oxide repeat units / chain','repeat_units',1,10000,1],
 ['Statistical segments / chain','segments',2,1000,1],
 ['Grafted and free end groups','end_groups','text'],
 ['Topology / coordinate reference','topology_reference','text'],
 ['Force-field reference','parameter_reference','text'],
]

/** Inline coating intent; no surface-library writes, generated atoms or scene preview. */
export function initNamdPegCoating({api,store,host=document.getElementById('namd-peg-surfaces')}={}) {
 if(!host)return null
 const enable=document.getElementById('md-peg-enable'),form=host.querySelector('form'),status=host.querySelector('[role=status]'),view=host.querySelector('[data-view-peg]')
 let designId, revision=0, timer=null, pending=null, chain=Promise.resolve(),disposed=false
 for(const [label,key,options,max,step] of FIELDS){
  const wrap=document.createElement('label');wrap.className='namd-surface-field';wrap.textContent=label
  const input=document.createElement(Array.isArray(options)?'select':'input');input.id=`md-peg-${key}`;input.name=key
  if(Array.isArray(options))for(const [value,text] of options)input.add(new Option(text,value))
  else{input.type=options==='text'?'text':'number';if(input.type==='number'){input.min=options;input.max=max;input.step=step || 'any';input.required=true}else input.maxLength=500}
  if(key.endsWith('_reference'))wrap.title='Optional draft note. Files and compatibility are not validated.'
  input.value=NAMD_PEG_DEFAULTS[key];wrap.append(input);form.append(wrap)
 }
 const spec=()=>{
  const result=namdPegFormSpec(form)
  result.repeat_units=Number(form.elements.repeat_units.value)
  result.segments=Number(form.elements.segments.value)
  if(document.getElementById('md-surface-enable')?.checked){result.material='graphene';result.pore_diameter_nm=Number(document.getElementById('md-surface-pore-diameter').value);result.layers=Number(document.getElementById('md-surface-layers').value)}
  return result
 }
 function paint(){
  const atomistic=form.elements.representation.value==='atomistic'
  for(const [key,hidden] of [['repeat_units',!atomistic],['segments',atomistic]]){form.elements[key].closest('label').hidden=hidden;form.elements[key].disabled=hidden}
  view.disabled=!enable.checked && !store?.getState()?.currentDesign?.metadata?.namd_peg_review
  try{const {chains}=namdPegEstimate(spec());status.textContent=enable.checked?`${chains.toLocaleString()} requested chains`:'Coating off.'}catch(e){status.textContent=e.message}
 }
 function emit(){window.dispatchEvent(new CustomEvent('nadoc:namd-peg-coating',{detail:{visible:view.checked,coating:null,designId}}))}
 function snapshot(){if(!form.reportValidity())throw Error('Correct the PEG coating parameters.');return {schema:'nadoc.namd_peg_coating.v1',enabled:enable.checked,spec:spec(),visible:view.checked}}
 function schedule(){
  paint();emit();revision++
  try{pending=snapshot()}catch{return}
  clearTimeout(timer);timer=setTimeout(flush,250)
 }
 async function flush(){
  clearTimeout(timer)
  const data=pending,id=designId,token=revision;pending=null
  if(!data || !id || !api.updateMetadata)return
  chain=chain.catch(()=>{}).then(async()=>{
   if(disposed || id!==designId || token!==revision)return
   try{await api.updateMetadata({namd_peg_coating:data,namd_peg_visible:data.visible})}
   catch(e){if(id===designId)status.textContent=`Could not save coating settings: ${e.message}`;throw e}
  })
  await chain.catch(()=>{})
 }
 function restore(data){
  const values={...NAMD_PEG_DEFAULTS,...data?.spec}
  for(const [,key] of FIELDS)form.elements[key].value=values[key]
  enable.checked=!!data && data.enabled!==false;view.checked=data?.visible!==false
  paint();emit()
 }
 const sync=()=>{const d=store?.getState()?.currentDesign;if(d?.id===designId)return;revision++;clearTimeout(timer);pending=null;designId=d?.id;restore(d?.metadata?.namd_peg_coating);view.checked=d?.metadata?.namd_peg_visible!==false;emit()}
 form.addEventListener('submit',e=>e.preventDefault());form.addEventListener('input',schedule);form.addEventListener('change',schedule)
 enable.addEventListener('change',schedule);view.addEventListener('change',schedule)
 const review=async()=>{
  const token=revision
  try{const data=snapshot();status.textContent='Checking coating…';const result=await api.reviewNamdPegSurface(data.spec);if(token===revision)status.textContent=`${result.summary.chains.toLocaleString()} chains · coating parameters checked. Atomistic preparation still requires validated assets.`}
  catch(e){if(token===revision)status.textContent=e.message}
 }
 host.querySelector('[data-review-coating]').addEventListener('click',review)
 const unsubscribe=store?.subscribe(sync);sync();paint()
 return {capture:snapshot,async apply(data){revision++;restore(data);schedule();await flush()},flush,
  dispose(){disposed=true;revision++;clearTimeout(timer);unsubscribe?.();enable.removeEventListener('change',schedule);view.removeEventListener('change',schedule);form.removeEventListener('input',schedule);form.removeEventListener('change',schedule)}}
}
