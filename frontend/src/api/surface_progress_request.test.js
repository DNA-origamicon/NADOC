import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

let progress, popup
beforeEach(async () => {
  vi.useFakeTimers(); vi.resetModules()
  document.body.innerHTML = ['op-progress','op-progress-header','op-progress-label','op-progress-meta','op-progress-fill','op-progress-track','op-progress-cancel'].map(id=>`<div id="${id}"></div>`).join('')
  progress = await import('./surface_progress_request.js')
  popup = await import('../ui/op_progress.js')
})
afterEach(()=>{ vi.useRealTimers(); document.body.innerHTML='' })

it('counts current stage work without inventing an overall time percentage', () => {
  expect(progress.isSurfaceComputation('/design/surface-bin?detail=chimerax')).toBe(true)
  expect(progress.isSurfaceComputation('/oxdna/jobs/a/display-surface-bin?align=true')).toBe(true)
  expect(progress.isSurfaceComputation('/surface-progress/12345678')).toBe(false)
  expect(progress.surfaceProgressView({stage:'Tiles',done:2,total:8,strand:{index:3,total:10}})).toEqual({label:'Strand 3 of 10 · Tiles · 2 / 8',fraction:.25})
  expect(progress.surfaceProgressView({stage:'Remeshing'}).fraction).toBeNull()
  expect(progress.surfaceProgressView({state:'complete'}).label).toBe('Receiving surface…')
})

it('passes the tracking id, displays measured progress, and cleans up polling', async () => {
  let finish
  const fetchImpl = vi.fn().mockResolvedValue({ok:true,json:async()=>({stage:'Tiles',done:3,total:8})})
  const run = vi.fn(()=>new Promise(resolve=>{finish=resolve}))
  const pending = progress.withSurfaceProgress('/design/surface-bin',{'X-NADOC-Doc':'doc-a'},run,{fetchImpl})
  expect(run.mock.calls[0][0]['X-NADOC-Surface-Progress']).toBeTruthy()
  await vi.advanceTimersByTimeAsync(250)
  expect(fetchImpl.mock.calls[0][1].headers['X-NADOC-Doc']).toBe('doc-a')
  expect(document.getElementById('op-progress-fill').style.width).toBe('37.5%')
  finish('mesh'); expect(await pending).toBe('mesh')
  expect(document.getElementById('op-progress').classList.contains('visible')).toBe(false)
  await vi.advanceTimersByTimeAsync(1000)
  expect(fetchImpl).toHaveBeenCalledTimes(1)
  expect(fetchImpl.mock.calls[0][1].signal.aborted).toBe(true)
})

it('does not overwrite a newer operation and restores the correct owner', async () => {
  const cancel = vi.fn()
  const a = popup.showOpProgress('First','start',{indeterminate:true,onCancel:cancel})
  const b = popup.showOpProgress('Second','new',{indeterminate:true})
  popup.updateOpProgress(a,{label:'old progress',fraction:.5})
  expect(document.getElementById('op-progress-label').textContent).toBe('new')
  popup.hideOpProgress(b)
  expect(document.getElementById('op-progress-label').textContent).toBe('old progress')
  expect(document.getElementById('op-progress-fill').style.width).toBe('50%')
  popup.hideOpProgress(b) // duplicate release cannot hide the remaining owner
  expect(document.getElementById('op-progress').classList.contains('visible')).toBe(true)
  document.getElementById('op-progress-cancel').click()
  expect(cancel).toHaveBeenCalledTimes(1)
  popup.updateOpProgress(a, {label:'Canceling'})
  expect(document.getElementById('op-progress-cancel').style.display).toBe('none')
  popup.hideOpProgress(a)
})

it('releases the popup after failure and leaves unrelated requests untracked', async () => {
  await expect(progress.withSurfaceProgress('/design/surface-bin',{},async()=>{throw new Error('failed')})).rejects.toThrow('failed')
  expect(document.getElementById('op-progress').classList.contains('visible')).toBe(false)
  const run=vi.fn().mockResolvedValue(4)
  expect(await progress.withSurfaceProgress('/jobs',{},run)).toBe(4)
  expect(run).toHaveBeenCalledWith({})
})
