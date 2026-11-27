export function traceStatusMessage(state){
  if(!state?.enabled)return ''
  const percent=state.work?`${Math.floor(100*state.work.fraction)}% · `:''
  let message
  if(state.error)message=`${state.error} Preview is using raster rendering. Check the selected preview renderer.`
  else if(state.state==='loading')message='Waiting for geometry to finish loading…'
  else if(state.state==='updating')message='Finishing the previous render before updating the view…'
  else if(state.state==='exporting')message='Rendering path-traced export…'
  else if(state.state==='interactive')message='Interactive tracing'
  else if(state.state==='waiting')message='Hold the view still to refine.'
  else if(state.work?.complete)message=`Ready · ${state.samples} / ${state.target} samples · ${(state.emSamples??0).toLocaleString()} EM points`
  else message=state.phase?.label||state.work?.detail||(state.state==='building'?'Preparing tracing scene…':`${state.samples??0} / ${state.target??0} samples`)
  return percent+message
}

/** Presentation only: work accounting belongs to the renderer, not its poller. */
export function initPhotoTraceProgress(root=document){
  const spinner=root.getElementById('photo-trace-spinner'),panel=root.getElementById('photo-trace-progress')
  const bar=root.getElementById('photo-trace-progress-bar'),label=root.getElementById('photo-path-status')
  return {sync(state){
    const work=state?.work,enabled=!!state?.enabled
    const busy=enabled&&!state.error&&(!work?.complete||['loading','building','updating','waiting','interactive','exporting'].includes(state.state))
    if(spinner){spinner.hidden=!busy;spinner.title=work?.detail||'Path tracing is working'}
    const message=traceStatusMessage(state)
    if(label)label.textContent=message
    if(!panel)return
    panel.hidden=!enabled
    const percent=Math.floor(100*(work?.fraction??0))
    bar.value=percent
    bar.setAttribute('aria-valuetext',message)
    panel.setAttribute('aria-busy',String(busy))

  }}
}
