import './md_surface_profiles.css'
import { generateMdSurfaceProfiles, getMdSurfaceProfiles } from '../api/client.js'
import { buildChartSpec, drawChart, SERIES_COLORS } from './metric_graph.js'
import { downloadText } from './metric_export_modal.js'

export function surfaceProfileSeries(result) {
  return {
    concentration: Object.entries(result.concentration_mM).flatMap(([face, species]) => Object.entries(species).map(([name, values]) => ({ label: `${face} ${name}`, points: values.map((v,i) => [result.distance_nm[i],v]) }))),
    charge: Object.entries(result.ionic_charge_e_nm3).map(([face, values]) => ({label:face,points:values.map((v,i) => [result.distance_nm[i],v])})),
    screening: result.residual_sheet_fraction ? [{label:'Pooled residual sheet fraction',points:result.residual_sheet_fraction.map((v,i) => [result.edge_distance_nm[i],v])}, ...(result.reference_residual_sheet_fraction ? [{label:'Linear Debye reference (bulk ε)',points:result.reference_residual_sheet_fraction.map((v,i) => [result.edge_distance_nm[i],v])}] : []), ...(result.screening_fit.available ? [{label:'Finite-slit fit',points:result.screening_fit.distance_nm.map((v,i) => [v,result.screening_fit.prediction[i]])}] : [])] : [],
  }
}

export function openSurfaceProfilePopup({ jobId, generate, load, doc = document }) {
  const dialog=doc.createElement('dialog')
  dialog.className='surface-profile-dialog'
  dialog.setAttribute('aria-label','Surface ions and screening')
  dialog.innerHTML=`<div class="surface-profile-heading"><strong>Surface ions and screening</strong><button data-close type="button">Close</button></div>
    <form><div class="surface-profile-inputs">
    <label>Bins <input name="bins" type="number" value="48" min="12" max="200" required></label>
    <label>Maximum sampled frames <input name="max_frames" type="number" value="256" min="8" max="2048" required></label>
    <label>Discard fraction <input name="discard_fraction" type="number" value="0.5" min="0" max="0.99" step="any" required></label>
    <label>Fit from (nm) <input name="fit_min_nm" type="number" value="0.6" min="0" step="any" required></label>
    <label>Fit to (nm) <input name="fit_max_nm" type="number" value="2.0" min="0.01" step="any" required></label>
    <label>Reference εᵣ <input name="dielectric" type="number" value="78.4" min="0.01" max="200" step="any" required></label></div>
    <div class="surface-profile-actions"><button data-calculate type="submit">Calculate</button><button data-export type="button" disabled>Export JSON</button></div></form>
    <div data-status role="status"></div><div data-summary></div><div data-plots></div>`
  doc.body.append(dialog)
  const el=k=>dialog.querySelector(`[data-${k}]`), form=dialog.querySelector('form')
  let result=null, revision=0, closed=false, edited=false
  const previousFocus=doc.activeElement
  const close=()=>{if(closed)return;closed=true;revision++;dialog.remove();previousFocus?.focus()}
  el('close').addEventListener('click',close)
  dialog.addEventListener('cancel',event=>{event.preventDefault();close()})
  dialog.addEventListener('click',event=>{if(event.target===dialog)close()})
  function render(value) {
    result=value;el('export').disabled=false
    const fit=value.screening_fit
    el('summary').textContent=`Last calculated: ${value.frames} sampled frames · bulk Na ${value.bulk_Na_mM.toFixed(1)} / Cl ${value.bulk_Cl_mM.toFixed(1)} mM · reference λD ${value.reference_debye_nm?.toFixed(3) ?? '—'} nm · ${fit.available ? `fit λ ${fit.lambda_nm.toFixed(3)} nm (R² ${fit.r_squared.toFixed(3)})` : fit.reason} · block λ: ${(value.block_lambda_nm || []).map(v=>v?.toFixed(3) ?? '—').join(', ')} nm. Diagnostic only; equilibration is not certified.`
    const plots=el('plots');plots.replaceChildren()
    const series=surfaceProfileSeries(value)
    for(const [key,title,units] of [['concentration','Ion concentration','mM'],['charge','Ionic charge density','e / nm³'],['screening','Uncompensated sheet fraction','fraction']]) {
      const canvas=doc.createElement('canvas');plots.append(canvas)
      drawChart(canvas,buildChartSpec({series:series[key].map((s,i)=>({...s,color:SERIES_COLORS[i%SERIES_COLORS.length]})),width:650,height:310,title,xLabel:'distance from wall (nm)',yLabel:units,zeroLine:true}))
    }
  }
  form.addEventListener('input',()=>{edited=true;el('status').textContent='Parameters changed. Click Calculate to update the graphs.'})
  form.addEventListener('submit',async event=>{
    event.preventDefault()
    if(!form.reportValidity())return
    const options=Object.fromEntries([...form.querySelectorAll('input')].map(input=>[input.name,Number(input.value)]))
    if(options.fit_max_nm<=options.fit_min_nm){el('status').textContent='Fit to must be greater than Fit from.';return}
    const token=++revision
    el('calculate').disabled=true;el('status').textContent='Calculating from complete trajectory frames…'
    try {
      const value=await generate(jobId,options)
      if(token!==revision)return
      render(value);el('status').textContent=edited ? 'Calculation complete. Graphs show the submitted parameters.' : 'Calculation complete.'
    } catch(error) {if(token===revision)el('status').textContent=`${error.message || 'Calculation failed.'}${result ? ' Previous graphs retained.' : ''}`}
    finally {if(token===revision)el('calculate').disabled=false}
  })
  el('export').addEventListener('click',()=>{if(result)downloadText(`surface_profiles_${jobId}.json`,JSON.stringify(result,null,2),'application/json')})
  const token=revision
  el('status').textContent='Loading saved profiles…'
  load(jobId).then(value=>{
    if(token!==revision)return
    if(!edited)for(const input of form.querySelectorAll('input'))if(value.options?.[input.name]!=null)input.value=value.options[input.name]
    render(value);el('status').textContent=edited ? 'Parameters changed. Click Calculate to update the graphs.' : 'Saved profiles loaded. Adjust parameters and click Calculate to recompute.'
  }).catch(()=>{if(token===revision)el('status').textContent='Choose parameters and click Calculate.'})
  if(dialog.showModal)dialog.showModal();else dialog.setAttribute('open','')
  return {close,focus:()=>el('calculate').focus()}
}

export function initMdSurfaceProfiles({ getSelectedJob, getJobs = () => [], root = document, generate, load } = {}) {
  const host=root.querySelector('#md-metrics-surface-profiles')
  if (!host) return {sync() {}}
  generate ??= generateMdSurfaceProfiles;load ??= getMdSurfaceProfiles
  host.innerHTML='<button data-open type="button">Surface ions and screening…</button>'
  let selected=null,popup=null
  function sync() {
    const job=getSelectedJob?.(); const id=job?.job_id || null
    let source=job; const seen=new Set()
    while(source?.parent_job_id && !source?.prep_params?.graphene_only && !seen.has(source.job_id)) { seen.add(source.job_id);source=getJobs?.()?.find(j=>j.job_id===source.parent_job_id) }
    host.hidden=!(source?.prep_params?.graphene_only && source?.prep_params?.graphene_pore_diameter_nm===0)
    if(id!==selected){popup?.close();popup=null;selected=id}
  }
  host.querySelector('[data-open]').addEventListener('click',()=>{
    if(!selected || host.hidden)return
    popup?.close()
    popup=openSurfaceProfilePopup({jobId:selected,generate,load,doc:host.ownerDocument})
  })
  sync()
  return {sync}
}
