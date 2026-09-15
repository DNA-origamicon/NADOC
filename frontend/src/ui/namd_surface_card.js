import './namd_surface_card.css'

const normals = { '-x': [1,0,0], '+x': [-1,0,0], '-y': [0,1,0], '+y': [0,-1,0], '-z': [0,0,1], '+z': [0,0,-1] }

/** Surface setup is separate from the immutable selected-job display descriptor. */
export function initNamdSurfaceCard({ root=document, onChange=()=>{}, onSetupPreview=()=>{} }={}) {
  const hard=root.querySelector('#md-hard-surface-enable')
  const pore=root.querySelector('#md-surface-enable')
  const charge=root.querySelector('#md-screening-enable')
  const peg=root.querySelector('#md-peg-enable')
  let job=null, prep={}, authorizedId=null, seed=null
  let lastSelection=null,lastPreview=null,setupActive=false
  const fields=['axis','offset','pore-diameter','layers','layer-spacing'].map(name=>root.querySelector(`#md-surface-${name}`)).filter(Boolean)
  const setupEnabled=()=>!!(hard?.checked || pore?.checked || charge?.checked)
  const value=(name,fallback)=>root.querySelector(`#md-surface-${name}`)?.value ?? fallback
  function dispatchChanged(type,detail,previous){
    const key=JSON.stringify(detail)
    if(key!==previous)window.dispatchEvent(new CustomEvent(type,{detail}))
    return key
  }
  const pegJob=()=>['peg_wall_qualification','peg_fast_relax'].includes(job?.run_kind)
  function emit() {
    const enabled=!!job?.job_id && authorizedId===job.job_id && (!!prep.graphene_nanopore || pegJob())
    // Setup previews never authorize a job/coating or change its immutable descriptor.
    const previewEnabled=enabled || (setupActive && setupEnabled())
    lastSelection=dispatchChanged('nadoc:namd-surface-selection', {
      enabled,previewEnabled,jobId:enabled?job.job_id:null,coating:enabled?prep.namd_peg_coating || null:null,
    },lastSelection)
    const p=enabled?prep:{
      graphene_pore_diameter_nm:pore?.checked?Number(value('pore-diameter',2.1)):0,
      graphene_layers:Number(value('layers',1)),graphene_layer_spacing_nm:Number(value('layer-spacing',.335)),
      graphene_surface_axis:value('axis',''),graphene_surface_offset_nm:Number(value('offset',0)),
    }
    lastPreview=dispatchChanged('nadoc:graphene-nanopore-preview', {
      enabled:previewEnabled && !pegJob(),
      poreDiameterNm:p.graphene_pore_diameter_nm ?? 2.1,
      layers:p.graphene_layers ?? 1,layerSpacingNm:p.graphene_layer_spacing_nm ?? .335,
      surface:normals[p.graphene_surface_axis]
        ? {dir:normals[p.graphene_surface_axis],positionNm:p.graphene_surface_offset_nm || 0,faceRelative:true}
        : seed || {dir:[0,1,0],positionNm:p.graphene_surface_offset_nm || 0,faceRelative:true},
    },lastPreview)
  }
  function sync() {
    for (const [id,toggle] of [['md-hard-surface-settings',hard],['md-screening-settings',charge],['md-nanopore-settings',pore],['md-peg-settings',peg]]) {
      const details=root.querySelector(`#${id}`)
      if(details)details.dataset.enabled=String(!!toggle?.checked)
    }
    const status=root.querySelector('#md-surface-ready')
    if(status)status.textContent=hard?.checked || pore?.checked || charge?.checked?'Surface configured for the next job.':'Surface off.'
    onChange(setupEnabled())
    emit()
  }
  function edit(){setupActive=true;if(!job && setupEnabled())onSetupPreview();sync()}
  function change(event) {
    setupActive=true
    if(event.target===hard && !hard.checked){
      const changed=[pore,charge,peg].filter(toggle=>toggle?.checked)
      // Clear dependencies together before notifying their controllers: otherwise
      // a still-checked sibling can turn the hard surface straight back on.
      for(const toggle of changed)toggle.checked=false
      for(const toggle of changed)toggle.dispatchEvent(new Event('change'))
    }
    else if((pore?.checked || charge?.checked || peg?.checked) && hard)hard.checked=true
    // The supported charge model is a closed wall, not a charged nanopore.
    if(event.target===pore && pore.checked && charge?.checked){charge.checked=false;charge.dispatchEvent(new Event('change'))}
    if(event.target===charge && charge.checked && pore)pore.checked=false
    if(!job && setupEnabled())onSetupPreview()
    sync()
  }
  for(const toggle of [hard,pore,charge,peg])toggle?.addEventListener('change',change)
  for(const field of fields){field.addEventListener('input',edit);field.addEventListener('change',edit)}
  sync()
  return {
    sync,
    enabled:()=>!!(hard?.checked || pore?.checked || charge?.checked),
    poreDiameter:value=>pore?.checked?value:0,
    restore(p={}){if(hard)hard.checked=!!p.graphene_nanopore;if(pore)pore.checked=!!p.graphene_nanopore && Number(p.graphene_pore_diameter_nm ?? 2.1)>0;sync()},
    select(next,params={},explicit=false){if(job?.job_id!==next?.job_id){setupActive=false;seed=null}job=next;prep=params;if(explicit)authorizedId=next?.job_id || null;else if(authorizedId!==next?.job_id)authorizedId=null;emit()},
    setSeed(value){seed=value;emit()},
    clear(){setupActive=false;job=null;prep={};authorizedId=null;seed=null;lastPreview=null;emit()},
    dispose(){for(const field of fields){field.removeEventListener('input',edit);field.removeEventListener('change',edit)}for(const toggle of [hard,pore,charge,peg])toggle?.removeEventListener('change',change)},
  }
}
