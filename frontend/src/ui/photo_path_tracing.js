import {initPhotoTraceProgress} from './photo_trace_progress.js'

export function stepTraceSamples(value,direction){
  const current=Math.max(1,Math.min(512,Number(value)||64))
  const power=direction>0?Math.floor(Math.log2(current))+1:Math.ceil(Math.log2(current))-1
  return Math.max(1,Math.min(512,2**power))
}

export function initPhotoPathTracing({mode,changed,root=document}) {
  const workProgress=initPhotoTraceProgress(root)
  const toggle=root.getElementById('photo-path-tracing'),samples=root.getElementById('photo-path-samples')
  const backend=root.getElementById('photo-trace-backend'),interactive=root.getElementById('photo-trace-interactive')
  const denoise=root.getElementById('photo-trace-denoise')
  const previewBackend=root.getElementById('photo-trace-preview-backend')
  const selectPreviewBackend=()=>{mode.setPathTracePreviewBackend?.(previewBackend.value);sync();changed()}
  previewBackend?.addEventListener('change',selectPreviewBackend)
  const selectDenoise=()=>{mode.setTraceDenoise?.(denoise.checked);sync();changed()}
  denoise?.addEventListener('change',selectDenoise)
  const selectInteractive=()=>{mode.setTraceInteractive?.(interactive.checked);sync();changed()}
  interactive?.addEventListener('change',selectInteractive)
  const up=root.getElementById('photo-path-samples-up'),down=root.getElementById('photo-path-samples-down')
  let draft=false
  const enable=async()=>{
    const wanted=toggle.checked
    if(wanted&&mode.confirmPathTracing){
      const choice=await mode.confirmPathTracing()
      if(choice==='cancel'||choice==='disable'){sync();changed();return}
    }
    mode.setPathTracing(wanted);sync();changed()
  }
  const edit=()=>{draft=true}
  const quality=()=>{
    if(!draft)return
    draft=false
    const value=Number(samples.value),previous=mode.getSettings().pathTraceSamples??64
    const next=samples.value.trim() && Number.isFinite(value)?Math.max(1,Math.min(512,Math.round(value))):previous
    if(next!==previous){mode.setPathTraceSamples(next);changed()}
    sync()
  }
  const step=direction=>{
    if(samples.disabled)return
    samples.focus();samples.value=String(stepTraceSamples(samples.value,direction));draft=true
  }
  const increase=()=>step(1),decrease=()=>step(-1),keepFocus=event=>event.preventDefault()
  const key=event=>{
    if(event.key==='Enter'){event.preventDefault();event.stopPropagation();quality()}
    if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();event.stopPropagation();step(event.key==='ArrowUp'?1:-1)}
  }
  const selectBackend=()=>{mode.setPathTraceExportBackend(backend.value);sync();changed()}
  function sync(){
    const settings=mode.getSettings(),state=mode.getPathTracingStatus?.()
    workProgress.sync(state)
    if(denoise)denoise.checked=settings.pathTraceDenoise!==false
    if(previewBackend){previewBackend.value=settings.pathTracePreviewBackend??'webgl';previewBackend.disabled=false}
    if(interactive)interactive.checked=settings.pathTraceInteractive!==false
    if(toggle)toggle.checked=!!settings.pathTracing
    if(samples){if(!draft)samples.value=String(settings.pathTraceSamples??64);samples.disabled=false}
    if(up)up.disabled=false
    if(down)down.disabled=false
    if(backend){backend.value=settings.pathTraceExportBackend??'webgl';backend.disabled=false}

  }
  toggle?.addEventListener('change',enable)
  samples?.addEventListener('input',edit);samples?.addEventListener('blur',quality);samples?.addEventListener('keydown',key)
  up?.addEventListener('mousedown',keepFocus);down?.addEventListener('mousedown',keepFocus)
  up?.addEventListener('click',increase);down?.addEventListener('click',decrease)
  backend?.addEventListener('change',selectBackend)
  sync()
  return {sync,dispose(){previewBackend?.removeEventListener('change',selectPreviewBackend);denoise?.removeEventListener('change',selectDenoise);interactive?.removeEventListener('change',selectInteractive);toggle?.removeEventListener('change',enable);backend?.removeEventListener('change',selectBackend)
    samples?.removeEventListener('input',edit);samples?.removeEventListener('blur',quality);samples?.removeEventListener('keydown',key)
    up?.removeEventListener('mousedown',keepFocus);down?.removeEventListener('mousedown',keepFocus)
    up?.removeEventListener('click',increase);down?.removeEventListener('click',decrease)}}
}
