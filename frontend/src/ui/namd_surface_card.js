import './namd_surface_card.css'

const normals = { '-x': [1,0,0], '+x': [-1,0,0], '-y': [0,1,0], '+y': [0,-1,0], '-z': [0,0,1], '+z': [0,0,-1] }

/** Surface setup is separate from the immutable selected-job display descriptor. */
export function initNamdSurfaceCard({ root=document, onChange=()=>{} }={}) {
  const hard=root.querySelector('#md-hard-surface-enable')
  const pore=root.querySelector('#md-surface-enable')
  const charge=root.querySelector('#md-screening-enable')
  const peg=root.querySelector('#md-peg-enable')
  let job=null, prep={}, authorizedId=null, seed=null
  const pegJob=()=>['peg_wall_qualification','peg_fast_relax'].includes(job?.run_kind)
  function emit() {
    const enabled=!!job?.job_id && authorizedId===job.job_id && (!!prep.graphene_nanopore || pegJob())
    window.dispatchEvent(new CustomEvent('nadoc:namd-surface-selection', {detail:{
      enabled,jobId:enabled?job.job_id:null,coating:enabled?prep.namd_peg_coating || null:null,
    }}))
    window.dispatchEvent(new CustomEvent('nadoc:graphene-nanopore-preview', {detail:{
      enabled:enabled && !!prep.graphene_nanopore && !pegJob(),
      poreDiameterNm:prep.graphene_pore_diameter_nm ?? 2.1,
      layers:prep.graphene_layers ?? 1,layerSpacingNm:prep.graphene_layer_spacing_nm ?? .335,
      surface:normals[prep.graphene_surface_axis]
        ? {dir:normals[prep.graphene_surface_axis],positionNm:prep.graphene_surface_offset_nm || 0,faceRelative:true}
        : seed || {dir:[0,1,0],positionNm:prep.graphene_surface_offset_nm || 0,faceRelative:true},
    }}))
  }
  function sync() {
    for (const [id,toggle] of [['md-hard-surface-settings',hard],['md-screening-settings',charge],['md-nanopore-settings',pore],['md-peg-settings',peg]]) {
      const details=root.querySelector(`#${id}`)
      if(details)details.dataset.enabled=String(!!toggle?.checked)
    }
    const status=root.querySelector('#md-surface-ready')
    if(status)status.textContent=hard?.checked || pore?.checked || charge?.checked?'Surface configured for the next job.':'Surface off.'
    onChange(!!(hard?.checked || pore?.checked || charge?.checked))
  }
  function change(event) {
    if(event.target===hard && !hard.checked){if(peg){peg.checked=false;peg.dispatchEvent(new Event('change'))}if(pore)pore.checked=false;if(charge){charge.checked=false;charge.dispatchEvent(new Event('change'))}}
    else if((pore?.checked || charge?.checked || peg?.checked) && hard)hard.checked=true
    // The supported charge model is a closed wall, not a charged nanopore.
    if(event.target===pore && pore.checked && charge){charge.checked=false;charge.dispatchEvent(new Event('change'))}
    if(event.target===charge && charge.checked && pore)pore.checked=false
    sync()
  }
  for(const toggle of [hard,pore,charge,peg])toggle?.addEventListener('change',change)
  sync();emit()
  return {
    sync,
    enabled:()=>!!(hard?.checked || pore?.checked || charge?.checked),
    poreDiameter:value=>pore?.checked?value:0,
    restore(p={}){if(hard)hard.checked=!!p.graphene_nanopore;if(pore)pore.checked=!!p.graphene_nanopore && Number(p.graphene_pore_diameter_nm ?? 2.1)>0;sync()},
    select(next,params={},explicit=false){job=next;prep=params;seed=null;if(explicit)authorizedId=next?.job_id || null;else if(authorizedId!==next?.job_id)authorizedId=null;emit()},
    setSeed(value){seed=value;emit()},
    clear(){job=null;prep={};authorizedId=null;seed=null;emit()},
    dispose(){for(const toggle of [hard,pore,charge,peg])toggle?.removeEventListener('change',change)},
  }
}
