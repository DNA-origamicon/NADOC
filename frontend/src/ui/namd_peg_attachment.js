/** Document attachment for workspace PEG drafts; removal detaches, never deletes the library. */
export function initNamdPegAttachment({host,api,store,onReset=()=>{}}) {
  const launch=host.querySelector('[data-new-surface]')
  let remove=host.querySelector('[data-remove-coating]'),view=host.querySelector('[data-view-peg]')
  if(!remove){remove=document.createElement('button');remove.dataset.removeCoating='';remove.textContent='Remove PEG coating';host.append(remove)}
  if(!view){const label=document.createElement('label');view=document.createElement('input');view.type='checkbox';view.dataset.viewPeg='';label.append(view,' View PEG');host.append(label)}
  const status=host.querySelector('[role=status]')
  let coating=null,visible=true,dirty=false,busy=false,designId=undefined
  const design=()=>store?.getState()?.currentDesign
  let emittedRecord,emittedVisible,emittedDesign
  const emit=()=>{
    if(emittedRecord===coating && emittedVisible===visible && emittedDesign===designId)return
    emittedRecord=coating;emittedVisible=visible;emittedDesign=designId
    window.dispatchEvent(new CustomEvent('nadoc:namd-peg-coating',{detail:{coating,visible,designId}}))
  }
  const error=e=>{if(status){status.hidden=false;status.textContent=e.message}}
  function render() {
    launch.textContent=coating || dirty?'Edit PEG coating':'Add PEG coating'
    launch.disabled=remove.disabled=busy
    remove.hidden=!(coating || dirty)
    remove.title='Remove this coating from the current surface. Saved library drafts remain available.'
    view.disabled=busy || !(coating || design()?.metadata?.namd_peg_review)
    view.checked=visible
  }
  async function persist(fields) {if(design()?.id && api.updateMetadata)await api.updateMetadata(fields)}
  function sync() {
    const d=design()
    if(designId!==d?.id){designId=d?.id;dirty=false;onReset()}
    if(store){coating=d?.metadata?.namd_peg_coating || null;visible=d?.metadata?.namd_peg_visible!==false}
    render();emit()
  }
  const unsubscribe=store?.subscribe(sync)
  remove.addEventListener('click',async()=>{
    if(busy)return
    busy=true;render()
    try {await persist({namd_peg_coating:null});coating=null;dirty=false;onReset();if(status){status.textContent='';status.hidden=true}emit()}
    catch(e){error(e)}finally{busy=false;render()}
  })
  view.addEventListener('change',async()=>{
    const previous=visible;visible=view.checked;busy=true;render();emit()
    try{await persist({namd_peg_visible:visible})}catch(e){visible=previous;error(e);emit()}finally{busy=false;render()}
  })
  sync()
  return {get:()=>coating,designId:()=>design()?.id,
    async set(record,expectedDesignId){
      if(design()?.id!==expectedDesignId)throw Error('Document changed. The coating remains saved in the library.')
      await persist({namd_peg_coating:record})
      if(design()?.id!==expectedDesignId)throw Error('Document changed. The coating remains saved in the library.')
      coating=record;dirty=false;render();emit()
    },
    render(value=dirty){dirty=value;render()},setBusy(value){busy=value;render()},
    dispose(){unsubscribe?.()},
  }
}
