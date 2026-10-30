import './md_box_solvent.css'

export const PREPARATION_KEYS = new Set(['padding_nm','box_mode','box_size_nm','salt_mode','mg_conc_mM','ion_conc_mM','graphene_temperature_K'])
const DEFAULTS = {sizing:'auto',padding:6,x:10,y:10,z:10,salt:'screening',na:0,mg:12.5,temperature:300}

/** Bulk-salt estimate only: excluded molecular volume/counterions require preparation. */
export function solventNumbers(dimensions, na, mg) {
  const volume = dimensions.reduce((a,b)=>a*b,1)
  const count = c => Math.round(.000602214076*c*volume)
  return {volume_nm3:volume,na:count(na),mg:count(mg),cl:count(na)+2*count(mg)}
}

/** Signed geometric clearance to each face, in the same frame as the solute. */
export function faceClearances(dimensions, center, bounds) {
  if(!bounds || !dimensions || !center)return null
  if(![...dimensions,...center,...bounds.min,...bounds.max].every(Number.isFinite))return null
  return dimensions.map((length,i)=>[
    bounds.min[i]-(center[i]-length/2),
    center[i]+length/2-bounds.max[i],
  ])
}

export function initBoxSolvent({api,store,root=document}={}) {
  const host=root.querySelector('#md-box-solvent-body')
  if(!host)return null
  const inputs=Object.fromEntries(Object.keys(DEFAULTS).map(k=>[k,host.querySelector(`#md-box-${k}`)]))
  const view=host.querySelector('#md-box-view-details'),status=host.querySelector('[role=status]'),boundary=host.querySelector('output')
  const periodic=host.querySelector('#md-box-view-periodic')
  const spinner=root.querySelector('#md-box-loading'),warningIcon=root.querySelector('#md-box-warning'),warningPanel=host.querySelector('#md-box-warnings')
  let loading=false,calculationWarning='',jobWarnings=[]
  const dismissed=new Set()
  function paintFeedback(){
    if(spinner)spinner.hidden=!loading
    host.setAttribute('aria-busy',String(loading))
    const warnings=[...(calculationWarning?[calculationWarning]:[]),...jobWarnings.filter(w=>!dismissed.has(w.key)).map(w=>`Previous preparation failed — ${w.name}: ${w.message}`)]
    if(warningIcon){warningIcon.hidden=!warnings.length;warningIcon.title=warnings.join('\n') || 'Box and solvent needs attention'}
    if(warningPanel){
      warningPanel.replaceChildren();warningPanel.hidden=!warnings.length
      for(const message of warnings){const p=document.createElement('p');p.textContent=message;warningPanel.append(p)}
      if(jobWarnings.some(w=>!dismissed.has(w.key))){const button=document.createElement('button');button.type='button';button.textContent='Dismiss previous job warnings';button.onclick=()=>{for(const w of jobWarnings)dismissed.add(w.key);paintFeedback()};warningPanel.append(button)}
    }
  }
  function openWarnings(event){event.stopPropagation();host.style.display='';root.querySelector('#md-box-solvent-arrow')?.classList.remove('is-collapsed');warningPanel?.scrollIntoView?.({block:'nearest'});if(stale)schedule?.()}
  warningIcon?.addEventListener('click',openWarnings)
  const sourceLabel=document.createElement('p');sourceLabel.id='md-box-source';host.prepend(sourceLabel)
  let selectedJob=null, selectedPreparation=null, selectedContext=null, jobMeta=null
  let preview=null,version=0,timer=null,saveTimer=null,designId=store?.getState()?.currentDesign?.id,disposed=false
  let pairActive=false,unpairedSizes=null
  let writes=Promise.resolve(),geometry=store?.getState()?.currentGeometry
  const isPair=()=>!!root.querySelector('#md-two-electrodes-enable')?.checked
  const isCharged=()=>!!root.querySelector('#md-screening-enable')?.checked
  const read=()=>Object.fromEntries(Object.entries(inputs).map(([k,el])=>[k,el.value]))
  function settings(){
    if(selectedJob && selectedPreparation)return {...selectedPreparation}
    const raw=read(),p={padding_nm:Number(raw.padding),box_mode:raw.sizing==='rotation'?'rotation':'bbox',salt_mode:raw.salt,box_size_nm:null,
      ion_conc_mM:raw.salt==='screening'?0:Number(raw.na),mg_conc_mM:raw.salt==='screening'?12.5:Number(raw.mg)}
    for(const input of Object.values(inputs))if(!input.disabled && (!input.checkValidity() || !input.value.trim()))throw Error('Correct the Box and solvent settings.')
    if(isCharged() || isPair())p.graphene_temperature_K=Number(raw.temperature)
    if(raw.sizing==='explicit')p.box_size_nm=['x','y','z'].map(k=>Number(raw[k]))
    return p
  }
  function pairBox(){
    const get=k=>Number(root.querySelector(`#md-two-electrodes-${k}`)?.value)
    const axis={x:0,y:1,z:2}[root.querySelector('#md-two-electrodes-axis')?.value]
    const dims=[0,0,0],lateral=[0,1,2].filter(i=>i!==axis)
    dims[axis]=get('gap');dims[lateral[0]]=get('width');dims[lateral[1]]=get('depth')
    if(!dims.every(v=>Number.isFinite(v) && v>0))throw Error('Correct the Two-electrode dimensions.')
    const cell=[...dims];cell[axis]*=3
    return {calculated_nm:cell,solvent_nm:dims,center_nm:[0,0,0],normal_axis:axis,boundary:'slab',padding_nm:0}
  }
  function surfaceContext(){
    const get=(id,fallback)=>root.querySelector(`#${id}`)?.value ?? fallback
    const enabled=['md-hard-surface-enable','md-surface-enable','md-screening-enable'].some(id=>root.querySelector(`#${id}`)?.checked)
    return {graphene_nanopore:enabled,graphene_only:isCharged(),graphene_surface_axis:get('md-surface-axis','') || null,
      graphene_surface_offset_nm:Number(get('md-surface-offset',0)),graphene_pore_diameter_nm:root.querySelector('#md-surface-enable')?.checked?Number(get('md-surface-pore-diameter',2.1)):0,
      graphene_layers:Number(get('md-surface-layers',1)),graphene_layer_spacing_nm:Number(get('md-surface-layer-spacing',.335)),graphene_sheet_margin_nm:Number(get('md-surface-sheet-margin',1.5))}
  }
  function emit(){
    let detail={enabled:false}
    try {
      const p=settings()
      if(preview){
        const dims=preview.selected_nm || preview.calculated_nm
        const solvent=preview.solvent_nm || dims
        detail={enabled:view.checked,periodicImages:!!periodic?.checked,dimensions: dims,solvent,center:preview.center_nm || [0,0,0],solute:preview.solute_bounds_nm || null,
          padding:preview.padding_nm ?? p.padding_nm,boundary:preview.boundary || 'periodic',normal_axis:preview.normal_axis,
          na:p.ion_conc_mM,mg:p.mg_conc_mM,numbers:solventNumbers(solvent,p.ion_conc_mM,p.mg_conc_mM),
          temperature:isCharged() || isPair()?Number(inputs.temperature.value):300,
          temperatureLabel:isCharged() || isPair()?'K':'K target · protocol-controlled',estimated:true}
        if(selectedJob){
          detail={...detail,solute:null,padding:null,estimated:false,source:'Prepared initial box',
            jobName:selectedJob.design_name,na:null,mg:null,temperature:null,
            numbers:jobMeta?.ready?{na:jobMeta.species?.NA,mg:jobMeta.species?.MG,cl:jobMeta.species?.CL}:null}
        }
      }
    }catch{}
    window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail}))
  }
  function paint(){
    sourceLabel.textContent=selectedJob?`Saved job: ${selectedJob.design_name || 'NAMD'} · ${new Date(selectedJob.created_at*1000).toLocaleString()} — initial prepared box`:'New preparation preview — not a saved job'
    const help=root.querySelector('#md-box-sizing-help');if(help)help.hidden=!!selectedJob
    const pair=!selectedJob && isPair(),explicit=inputs.sizing.value==='explicit'
    if(pair && !pairActive)unpairedSizes=['x','y','z'].map(k=>inputs[k].value)
    if(!pair && pairActive && unpairedSizes)for(const [i,k] of ['x','y','z'].entries())inputs[k].value=unpairedSizes[i]
    pairActive=pair
    inputs.sizing.disabled=inputs.padding.disabled=pair
    for(const k of ['x','y','z'])inputs[k].disabled=pair || !explicit
    inputs.na.disabled=inputs.mg.disabled=inputs.salt.value==='screening'
    inputs.temperature.disabled=!(isCharged() || pair)
    if(inputs.temperature.disabled)inputs.temperature.value=300
    inputs.temperature.title=inputs.temperature.disabled?'Ordinary DNA relaxation targets 300 K; stage temperatures remain controlled by the protocol.':'Target temperature for the surface control.'
    boundary.textContent=selectedJob?'Saved periodic cell; dimensions shown are before pressure equilibration.':pair?'Slab: lateral periodic · normal vacuum padding (3×)':'Periodic on all six faces'
    if(selectedJob)for(const input of Object.values(inputs))input.disabled=true
    if(preview && (selectedJob || pair || !explicit))for(const [i,k] of ['x','y','z'].entries())inputs[k].value=(preview.selected_nm || preview.calculated_nm)[i].toFixed(3)
    const clearance=host.querySelector('#md-box-clearance')
    if(clearance){
      const gaps=!selectedJob && preview && faceClearances(preview.solvent_nm || preview.selected_nm || preview.calculated_nm,preview.center_nm,preview.solute_bounds_nm)
      clearance.textContent=selectedJob?'Initial package box; pressure equilibration changes its dimensions. Face clearances require the matching simulation coordinates.':gaps?`Water clearance to faces (nm): ${gaps.map((pair,i)=>`${'XYZ'[i]}− ${pair[0].toFixed(2)} / ${'XYZ'[i]}+ ${pair[1].toFixed(2)}`).join(' · ')}`:'Water clearance to faces: unavailable until the structure and box are calculated.'
    }
    paintFeedback();emit()
  }
  async function calculate(){
    const current=++version
    preview=null;loading=true;calculationWarning='';status.textContent='Calculating box dimensions and solvent details…';paint()
    try{
      const p=settings()
      if(selectedJob){
        const job=selectedJob
        const result=await api.getMdSolventMeta(job.job_id)
        if(current!==version || disposed)return
        if(!result?.box_nm?.every(v=>Number.isFinite(v) && v>0) || result.box_nm.length!==3)throw Error('Saved box dimensions unavailable for this job. No default box is substituted.')
        jobMeta=result;preview={selected_nm:[...result.box_nm],boundary:'periodic'}
        const electrode=selectedContext?.two_electrodes
        if(electrode){
          const axis={x:0,y:1,z:2}[electrode.normal]
          if(axis!=null){preview.boundary='slab';preview.normal_axis=axis;preview.solvent_nm=[...result.box_nm];preview.solvent_nm[axis]=electrode.gap_nm}
        }
        status.textContent=`${job.design_name || 'Selected job'} · ${new Date(job.created_at*1000).toLocaleString()} — prepared initial box from saved package. ${result.ready?`Actual ions: Mg ${result.species?.MG ?? 0}, Cl ${result.species?.CL ?? 0}, Na ${result.species?.NA ?? 0}.`:'Ion counts unavailable.'} Open New job to configure a new preparation.`
        return
      }
      if(isPair())preview=pairBox()
      else {
        const result=await api.fetchProtocolBoxPreview({protocol:'mgh',...surfaceContext(),...p})
        if(current!==version || disposed)return
        if(!result?.box_preview)throw Error(result?.warnings?.join(' ') || 'Choose explicit dimensions for an empty system, or load a structure to fit.')
        preview=result.box_preview
      }
      calculationWarning=(preview.sizing_notes || []).filter(Boolean).join(' ')
      status.textContent=isPair()?'Cell dimensions follow Two-electrode settings; salt and temperature are setup intent until qualification.':'New preparation preview — not a saved simulation box. Ion counts estimate added salt; preparation also adds neutralizing ions.'
    }catch(e){if(current===version){calculationWarning=e.message;status.textContent='Box calculation could not finish. Review the warning above.'}}
    finally{if(current===version && !disposed){loading=false;paint()}}
  }
  // The estimate only feeds this section's numbers and the optional "View details"
  // overlay (job preparation recomputes the box on the server). It asks the backend to
  // build a full atomistic model — ~20 s on a large design — so never do it while the
  // section is collapsed: it raced the geometry fetch on every design open. A collapsed
  // section just goes stale and recalculates when expanded.
  let stale=false
  const wanted=()=>host.style.display!=='none' || !!view?.checked || !!periodic?.checked
  function schedule(){
    clearTimeout(timer);version++;preview=null;calculationWarning='';paint()
    if(!wanted()){stale=true;loading=false;paintFeedback();emit();return}
    stale=false;loading=true;status.textContent='Calculating box dimensions and solvent details…';paintFeedback();emit();timer=setTimeout(calculate,250)
  }
  function save(){
    clearTimeout(saveTimer)
    const id=designId,values=read()
    saveTimer=setTimeout(()=>{if(!id || id!==designId || disposed)return;writes=writes.then(async()=>{if(id===designId && !disposed){const saved=await api.updateMetadata?.({namd_box_solvent:values},{skipGeometry:true});if(!saved)throw Error('Metadata update failed')}}).catch(e=>{status.textContent=`Could not save preparation settings: ${e.message}`})},400)
  }
  function change(event){
    if(event.target===view || event.target===periodic){if((view.checked || periodic?.checked) && stale)schedule();else emit();return}
    if(event.target===inputs.sizing && inputs.sizing.value==='auto')inputs.padding.value=DEFAULTS.padding
    if(host.contains(event.target)){
      // A saved setup preset can dispatch input events even on disabled controls.
      // That is a new preparation intent, never an edit to the selected package.
      if(selectedJob){selectedJob=null;selectedPreparation=null;jobMeta=null;for(const input of Object.values(inputs))input.disabled=false}
      if(event.target===inputs.salt && inputs.salt.value==='screening'){inputs.na.value=0;inputs.mg.value=12.5}paint();schedule();save()}
    else if(event.target?.closest?.('#md-surface-body')){paint();schedule()}
  }
  root.addEventListener('input',change);root.addEventListener('change',change)
  const header=root.querySelector('#md-box-solvent-toggle')
  header?.addEventListener('click',()=>{const open=host.style.display==='none';host.style.display=open?'':'none';root.querySelector('#md-box-solvent-arrow')?.classList.toggle('is-collapsed',!open);if(open && stale)schedule()})
  function restore(p={}){
    selectedJob=null;selectedPreparation=null;jobMeta=null
    for(const input of Object.values(inputs))input.disabled=false
    const values={...DEFAULTS,padding:p.padding_nm ?? DEFAULTS.padding,sizing:p.box_size_nm?.every(v=>v!=null)?'explicit':p.box_mode || DEFAULTS.sizing,
      salt:p.salt_mode || DEFAULTS.salt,na:p.ion_conc_mM ?? DEFAULTS.na,mg:p.mg_conc_mM ?? DEFAULTS.mg,temperature:p.graphene_temperature_K ?? DEFAULTS.temperature}
    if(p.box_size_nm)for(const [i,k] of ['x','y','z'].entries())values[k]=p.box_size_nm[i] ?? DEFAULTS[k]
    for(const [k,v] of Object.entries(values))inputs[k].value=v
    paint();schedule()
  }
  function restoreDocument(){
    selectedJob=null;selectedPreparation=null;jobMeta=null
    for(const input of Object.values(inputs))input.disabled=false
    jobWarnings=[];dismissed.clear()
    const saved=store?.getState()?.currentDesign?.metadata?.namd_box_solvent || DEFAULTS
    for(const k of Object.keys(DEFAULTS))inputs[k].value=saved[k] ?? DEFAULTS[k]
    view.checked=false;if(periodic)periodic.checked=false;paint();schedule()
  }
  const unsub=store?.subscribe(()=>{const state=store.getState(),id=state?.currentDesign?.id;if(id!==designId){designId=id;geometry=state.currentGeometry;clearTimeout(saveTimer);restoreDocument()}else if(state.currentGeometry!==geometry){geometry=state.currentGeometry;if(!selectedJob)schedule()}})
  restoreDocument()
  return {keys:PREPARATION_KEYS,payload(){const p=settings();if(!selectedJob && isPair())p.box_size_nm=pairBox().calculated_nm;return p},
    setJobWarnings(warnings){jobWarnings=warnings || [];paintFeedback()},
    restore,
    selectJob(job,prep={}){
      clearTimeout(saveTimer)
      restore(prep)
      if(!job || job.status==='draft')return
      selectedPreparation=settings();selectedJob=job;selectedContext=prep;jobMeta=null
      if(prep.padding_nm==null)inputs.padding.value=''
      for(const k of ['x','y','z'])inputs[k].value=''
      schedule()
    },
    clearJob(){if(selectedJob)restoreDocument()},
    beginPreparation(){if(selectedJob)restoreDocument()},
    refresh:schedule,summary:()=>isPair()?'Box and solvent: dimensions linked to Two-electrode settings.':`Box and solvent: ${inputs.sizing.value==='explicit'?['x','y','z'].map(k=>inputs[k].value).join(' × ')+' nm':`automatic ${settings().box_mode==='rotation'?'rotation-safe':'bounding-box'} fit; final dimensions set during preparation`}; NaCl ${settings().ion_conc_mM} mM; MgCl₂ ${settings().mg_conc_mM} mM. Edit in the sidebar.`,
    acceptPreview(value){if(!selectedJob && value && inputs.sizing.value!=='explicit' && !isPair()){preview={...preview,...value,center_nm:preview?.center_nm || value.center_nm,solute_bounds_nm:preview?.solute_bounds_nm || value.solute_bounds_nm};paint()}},
    dispose(){sourceLabel.remove();disposed=true;loading=false;paintFeedback();warningIcon?.removeEventListener('click',openWarnings);version++;clearTimeout(timer);clearTimeout(saveTimer);unsub?.();root.removeEventListener('input',change);root.removeEventListener('change',change);window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail:{enabled:false}}))}}
}
