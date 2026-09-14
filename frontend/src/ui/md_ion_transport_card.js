import { initMdIonTransportGeneration } from './md_ion_transport_generation.js'
import { getMdIonTransportAnalysis } from '../api/client.js'
import { openIonTransportPopup, ionTransportSeries } from './ion_transport_popup.js'
import { openMetricExportModal, downloadText, downloadHref } from './metric_export_modal.js'
import { buildChartSpec, drawChart } from './metric_graph.js'

export function mdJobNanoporeState(job) {
  const hasPore = !!job?.prep_params?.graphene_nanopore || job?.spawn_params?.ion_transport_mode === 'voltage'
  const analyzable = job?.run_kind === 'production' && job?.spawn_params?.ion_transport_mode === 'voltage'
  return { hasPore, analyzable }
}

export async function exportIonTransport(result, jobId) {
  const choice=await openMetricExportModal()
  if(!choice)return
  const groups=ionTransportSeries(result)
  if(choice.data) {
    const quote=value=>'"'+String(value).replaceAll('"','""')+'"'
    const rows=['metric,series,time_ns,value,unit']
    for(const [metric,series] of Object.entries(groups))for(const s of series)for(const [time,value] of s.points)rows.push([metric,s.label,time,value,metric==='current'?'nA':'net crossings'].map(quote).join(','))
    downloadText(`ion_transport_${jobId}.csv`,rows.join('\n'))
  }
  if(choice.png)for(const [key,title,units] of [['current','Electrical current','current (nA)'],['crossings','Aperture-validated crossings','cumulative net crossings']]) {
    const canvas=document.createElement('canvas')
    drawChart(canvas,buildChartSpec({series:groups[key],width:900,height:450,title,xLabel:'simulation time (ns)',yLabel:units,zeroLine:true}))
    downloadHref(`ion_transport_${jobId}_${key}.png`,canvas.toDataURL('image/png'))
  }
}

export function initMdIonTransportCard({getSelectedJob,root=document,generate=getMdIonTransportAnalysis,display=openIonTransportPopup,exportResult=exportIonTransport}) {
  const el=key=>root.getElementById(`md-metrics-ion-transport-${key}`)
  const row=el('row'),gen=el('gen'),show=el('display'),save=el('export'),status=el('status')
  const generation=initMdIonTransportGeneration(status)
  let selected=null,busy=false,revision=0
  const results=new Map()
  function sync() {
    const job=getSelectedJob?.(),id=job?.job_id ?? null,state=mdJobNanoporeState(job)
    if(id!==selected){selected=id;revision++;busy=false;generation.cancel();if(status)status.textContent=''}
    if(row)row.style.display=state.hasPore?'':'none'
    if(gen)gen.disabled=!state.analyzable || busy
    if(show)show.disabled=!state.analyzable || busy || !results.has(id)
    if(save)save.disabled=!state.analyzable || busy || !results.has(id)
    for(const button of [gen,show,save])if(button){button.style.color=button.disabled?'#6e7681':'#c9d1d9';button.style.cursor=button.disabled?'default':'pointer'}
    if(status && !busy)status.textContent=!state.analyzable && state.hasPore
      ? 'Available after spawning and running a voltage-driven production job.'
      : results.has(id) ? `${Number(results.get(id).mean_current_nA || 0).toFixed(4)} nA mean · ${results.get(id).frames || 0} frames` : ''
  }
  gen?.addEventListener('click',async()=>{
    if(!mdJobNanoporeState(getSelectedJob?.()).analyzable || busy)return
    const id=selected,token=++revision
    busy=true;sync();if(status)status.textContent='Generating ion-transport measurements…'
    let errorMessage=null
    try {const result=await generation.run(id,generate);if(token===revision)results.set(id,result)}
    catch(error){errorMessage=error.message || 'Ion-transport analysis failed.'}
    finally {if(token===revision){busy=false;sync();if(errorMessage && status)status.textContent=errorMessage+(results.has(id)?' Previous results retained.':'')}}
  })
  show?.addEventListener('click',()=>{if(!show.disabled && results.has(selected))display(results.get(selected))})
  save?.addEventListener('click',async()=>{
    if(save.disabled || !results.has(selected))return
    const token=revision
    try {await exportResult(results.get(selected),selected)}
    catch(error){if(token===revision && status)status.textContent=error.message || 'Export failed.'}
  })
  sync()
  return {sync}
}
