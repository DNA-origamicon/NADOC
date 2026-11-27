import {it,expect} from 'vitest'
import {initPhotoTraceProgress,traceStatusMessage} from './photo_trace_progress.js'
import {createTraceWorkProgress} from '../scene/photo_renderer/trace_work_progress.js'
it('shows measured work, a busy spinner and one accessible status; stops on completion, error or disable',()=>{
  document.body.innerHTML='<span id="photo-trace-spinner"></span><div id="photo-trace-progress"><progress id="photo-trace-progress-bar" max="100"></progress><div id="photo-path-status"></div></div>'
  const ui=initPhotoTraceProgress(),work=createTraceWorkProgress('optix',8)
  const state={enabled:true,state:'building',work:work.get()},spinner=document.getElementById('photo-trace-spinner'),bar=document.querySelector('progress')
  ui.sync(state);expect(spinner.hidden).toBe(false);expect(bar.value).toBe(0)
  work.event({stage:'snapshot',fraction:.5});state.work=work.get();ui.sync(state)
  expect(bar.value).toBe(10);expect(bar.getAttribute('aria-valuetext')).toContain('10%')
  expect(document.getElementById('photo-path-status').textContent).toBe('10% · Scene snapshot')
  state.error='Disconnected';ui.sync(state);expect(spinner.hidden).toBe(true)
  state.error='';state.state='tracing';work.event({stage:'display',fraction:1});state.work=work.get();ui.sync(state)
  expect(spinner.hidden).toBe(true);expect(bar.value).toBe(100)
  state.enabled=false;ui.sync(state);expect(document.getElementById('photo-trace-progress').hidden).toBe(true)
  document.body.replaceChildren()
})

it('unifies progress, phase, readiness and actionable errors in one message',()=>{
  const state={enabled:true,state:'tracing',samples:8,target:8,emSamples:0,work:{fraction:.5},phase:{label:'Uploading scene'}}
  expect(traceStatusMessage(state)).toBe('50% · Uploading scene')
  expect(traceStatusMessage({...state,work:{fraction:1,complete:true}})).toBe('100% · Ready · 8 / 8 samples · 0 EM points')
  expect(traceStatusMessage({...state,error:'Connection lost'})).toContain('Connection lost Preview is using raster rendering')
  expect(traceStatusMessage({...state,state:'updating'})).toContain('Finishing the previous render')
  expect(traceStatusMessage({...state,enabled:false})).toBe('')
})
