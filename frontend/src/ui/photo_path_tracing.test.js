import { it,expect,vi } from 'vitest'
import { initPhotoPathTracing, stepTraceSamples } from './photo_path_tracing.js'
it('controls the real settings, reports fallback and removes listeners on disposal',()=>{
  document.body.innerHTML='<input id="photo-path-tracing" type="checkbox"><input id="photo-path-samples"><div id="photo-path-status"></div>'
  const settings={pathTracing:false,pathTraceSamples:64},changed=vi.fn()
  const mode={getSettings:()=>settings,setPathTracing:v=>settings.pathTracing=v,setPathTraceSamples:v=>settings.pathTraceSamples=Number(v),
    getPathTracingStatus:()=>({enabled:settings.pathTracing,error:'No GPU'})}
  const ui=initPhotoPathTracing({mode,changed}),toggle=document.querySelector('#photo-path-tracing'),samples=document.querySelector('#photo-path-samples')
  toggle.click();expect(settings.pathTracing).toBe(true);expect(samples.disabled).toBe(false)
  samples.value='128';samples.dispatchEvent(new Event('input'));samples.dispatchEvent(new Event('blur'));expect(settings.pathTraceSamples).toBe(128)
  expect(document.querySelector('#photo-path-status').textContent).toContain('raster')
  ui.dispose();toggle.click();expect(settings.pathTracing).toBe(true);document.body.replaceChildren()
})
it('allows export settings to be chosen before enabling tracing',()=>{
  document.body.innerHTML='<input id="photo-path-tracing" type="checkbox"><select id="photo-trace-backend"><option value="webgl">WebGL</option><option value="webgpu">WebGPU</option></select>'
  const settings={pathTracing:true,pathTraceExportBackend:'webgl'},changed=vi.fn()
  const mode={getSettings:()=>settings,setPathTraceExportBackend:v=>settings.pathTraceExportBackend=v,setPathTracing:v=>settings.pathTracing=v}
  const ui=initPhotoPathTracing({mode,changed}),select=document.querySelector('select')
  select.value='webgpu';select.dispatchEvent(new Event('change'));expect(settings.pathTraceExportBackend).toBe('webgpu')
  expect(changed).toHaveBeenCalledOnce()
  document.querySelector('input').click();expect(select.disabled).toBe(false)
  select.value='webgl';select.dispatchEvent(new Event('change'));expect(settings.pathTraceExportBackend).toBe('webgl')
  ui.dispose();document.body.replaceChildren()
})

it('keeps a draft through status refreshes and commits only on blur or Enter',()=>{
  document.body.innerHTML='<input id="photo-path-samples" type="number"><button id="photo-path-samples-up"></button><button id="photo-path-samples-down"></button>'
  const settings={pathTracing:false,pathTraceSamples:64},changed=vi.fn()
  const mode={getSettings:()=>settings,setPathTraceSamples:vi.fn(v=>settings.pathTraceSamples=v)}
  const ui=initPhotoPathTracing({mode,changed}),input=document.querySelector('input')
  input.focus();input.value='2';input.dispatchEvent(new Event('input'));ui.sync()
  expect(input.value).toBe('2');expect(settings.pathTraceSamples).toBe(64)
  input.value='256';input.dispatchEvent(new Event('input'));ui.sync()
  expect(input.value).toBe('256');expect(changed).not.toHaveBeenCalled()
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))
  expect(settings.pathTraceSamples).toBe(256);expect(changed).toHaveBeenCalledOnce()
  input.blur();expect(changed).toHaveBeenCalledOnce()
  input.focus();input.value='';input.dispatchEvent(new Event('input'));ui.sync();expect(input.value).toBe('')
  input.blur();expect(input.value).toBe('256');expect(changed).toHaveBeenCalledOnce()
  input.focus();input.value='100';input.dispatchEvent(new Event('input'));input.blur();expect(settings.pathTraceSamples).toBe(100)
  input.focus();input.value='900';input.dispatchEvent(new Event('input'));input.blur();expect(settings.pathTraceSamples).toBe(512)
  ui.dispose();input.value='32';input.dispatchEvent(new Event('input'));input.dispatchEvent(new Event('blur'))
  expect(settings.pathTraceSamples).toBe(512);document.body.replaceChildren()
})
it('steps draft samples with both buttons and keyboard without premature commits',()=>{
  document.body.innerHTML='<input id="photo-path-samples" type="number"><button id="photo-path-samples-up"></button><button id="photo-path-samples-down"></button>'
  const settings={pathTracing:false,pathTraceSamples:64},changed=vi.fn()
  const mode={getSettings:()=>settings,setPathTraceSamples:v=>settings.pathTraceSamples=v}
  const ui=initPhotoPathTracing({mode,changed}),input=document.querySelector('input'),up=document.querySelector('#photo-path-samples-up')
  up.click();ui.sync();expect(input.value).toBe('128')
  up.click();expect(input.value).toBe('256');expect(settings.pathTraceSamples).toBe(64)
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown'}));expect(input.value).toBe('128')
  document.querySelector('#photo-path-samples-down').click();expect(input.value).toBe('64')
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp'}));input.blur();expect(settings.pathTraceSamples).toBe(128)
  ui.dispose();up.click();expect(input.value).toBe('128');document.body.replaceChildren()
})
it('steps to the next power of two in either direction and respects sample limits',()=>{
  for(const [value,direction,expected] of [[64,1,128],[128,1,256],[256,-1,128],[100,1,128],[100,-1,64],[1,-1,1],[512,1,512]])
    expect(stepTraceSamples(value,direction)).toBe(expected)
})

it('keeps interactive settings available without the removed metrics panel',()=>{
  document.body.innerHTML='<input type="checkbox" id="photo-trace-interactive">'
  const settings={pathTracing:false},mode={getSettings:()=>settings,setTraceMetricsEnabled:vi.fn(),setTraceInteractive:v=>settings.pathTraceInteractive=v}
  const ui=initPhotoPathTracing({mode,changed:vi.fn()}),toggle=document.querySelector('input')
  expect(toggle.checked).toBe(true);toggle.click();expect(settings.pathTraceInteractive).toBe(false)
  expect(mode.setTraceMetricsEnabled).not.toHaveBeenCalled()
  ui.dispose();document.body.replaceChildren()
})

it('sets denoising before tracing and removes the comparison control listener',()=>{
  document.body.innerHTML='<input type="checkbox" id="photo-trace-denoise">'
  const settings={pathTracing:false},changed=vi.fn(),mode={getSettings:()=>settings,setTraceDenoise:v=>settings.pathTraceDenoise=v}
  const ui=initPhotoPathTracing({mode,changed}),toggle=document.querySelector('input')
  expect(toggle.checked).toBe(true);toggle.click();expect(settings.pathTraceDenoise).toBe(false)
  toggle.click();expect(settings.pathTraceDenoise).toBe(true);expect(changed).toHaveBeenCalledTimes(2)
  ui.dispose();toggle.click();expect(settings.pathTraceDenoise).toBe(true);document.body.replaceChildren()
})

it('selects native preview before tracing independently of export and cleans up',()=>{
  document.body.innerHTML='<select id="photo-trace-preview-backend"><option value="webgl">WebGL</option><option value="optix">Native</option></select>'
  const settings={pathTracing:false,pathTraceExportBackend:'webgpu'},changed=vi.fn()
  const mode={getSettings:()=>settings,setPathTracePreviewBackend:v=>settings.pathTracePreviewBackend=v}
  const ui=initPhotoPathTracing({mode,changed}),select=document.querySelector('select')
  expect(select.value).toBe('webgl');expect(select.disabled).toBe(false)
  select.value='optix';select.dispatchEvent(new Event('change'));ui.sync()
  expect(settings.pathTracePreviewBackend).toBe('optix');expect(settings.pathTraceExportBackend).toBe('webgpu')
  expect(changed).toHaveBeenCalledOnce();ui.dispose()
  select.value='webgl';select.dispatchEvent(new Event('change'));expect(settings.pathTracePreviewBackend).toBe('optix')
  document.body.replaceChildren()
})

it('shows actual compile and native progress stages instead of a frozen waiting message',()=>{
  document.body.innerHTML='<div id="photo-path-status"></div>'
  const state={enabled:true,backend:'webgl',state:'building',phase:{label:'Compiling GPU tracing shader…'}}
  const mode={getSettings:()=>({}),getPathTracingStatus:()=>state}
  const ui=initPhotoPathTracing({mode,changed:vi.fn()}),status=document.querySelector('div')
  expect(status.textContent).toBe(state.phase.label)
  Object.assign(state,{backend:'optix',state:'tracing',diagnostics:{pending:true},phase:{label:'OptiX · 16/64 samples'}})
  ui.sync();expect(status.textContent).toBe('OptiX · 16/64 samples')
  state.state='updating';ui.sync();expect(status.textContent).toContain('previous render')
  state.state='tracing'
  Object.assign(state,{samples:64,target:64,emSamples:0,diagnostics:{pending:false},phase:null})
  ui.sync();expect(status.textContent).toContain('64 / 64 samples')
  ui.dispose();document.body.replaceChildren()
})
