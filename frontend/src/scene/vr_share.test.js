import { it, expect, vi, afterEach } from 'vitest'
import { createVRShare } from './vr_share.js'
import { initPresentationControls } from '../viewer/presentation_controls.js'
afterEach(() => { document.body.innerHTML = '' })
it('controls only an active desktop presentation and deduplicates events', async () => {
  const onPerspective = vi.fn(), onEnd = vi.fn(), request = vi.fn(async () => ({ ok: true }))
  const controls = initPresentationControls({ onPerspective, onEnd })
  const vr = createVRShare({ request })
  await vr.activate({ sequence: 1, action: 'resume' })
  expect(onPerspective).not.toHaveBeenCalled()
  controls.setActive(true); controls.setPerspective(true)
  await vr.activate({ sequence: 2, action: 'pause' })
  await vi.waitFor(() => expect(controls.perspective).toBe(false))
  await vr.activate({ sequence: 2, action: 'resume' })
  expect(onPerspective).toHaveBeenCalledTimes(1)
  await vr.activate({ sequence: 3, action: 'resume' })
  await vi.waitFor(() => expect(controls.perspective).toBe(true))
  await vr.activate({ sequence: 4, action: 'create' })
  expect(onPerspective).toHaveBeenCalledTimes(2)
  await vr.activate({ sequence: 5, action: 'end' })
  expect(onEnd).toHaveBeenCalledOnce()
  expect(request.mock.calls.every(([url]) => url === '/api/vr/share-controls')).toBe(true)
  controls.dispose()
})
it('keeps failed perspective state retryable and exposes desktop errors', async () => {
  const controls = initPresentationControls({ onPerspective: async () => { throw Error('Offline') }, onEnd: vi.fn() })
  controls.setActive(true)
  const vr = createVRShare({ request: async () => ({ ok: true }) })
  await vr.activate({ sequence: 1, action: 'resume' })
  await vi.waitFor(() => expect(vr.state().failed).toBe(true))
  expect(vr.state().perspective).toBe(false)
  expect(vr.state().busy).toBe(false)
  controls.dispose()
})
it('VR admits through the same desktop action, deduplicates it, and reports counts', async () => {
  const onAdmit=vi.fn(),controls=initPresentationControls({onAdmit,onEnd:vi.fn(),onPerspective:vi.fn()})
  controls.setActive(true);controls.setAdmission({active:16,waiting:8,guests:[]})
  const vr=createVRShare({request:async()=>({ok:true})})
  await vr.activate({sequence:1,action:'admit'});await vr.activate({sequence:1,action:'admit'})
  expect(onAdmit).toHaveBeenCalledOnce();expect(vr.state()).toMatchObject({activeGuests:16,waitingGuests:8});controls.dispose()
})

it('perspective lock does not block audience admission',async()=>{
 const onAdmit=vi.fn(),controls=initPresentationControls({onAdmit,onEnd:vi.fn(),onPerspective:vi.fn()})
 controls.setActive(true);document.querySelector('.presentation-view-lock').click()
 await vi.waitFor(()=>expect(controls.viewLocked).toBe(true))
 const vr=createVRShare({request:async()=>({ok:true})})
 expect(vr.state()).toMatchObject({busy:false,perspectiveAvailable:false})
 await vr.activate({sequence:1,action:'admit'});expect(onAdmit).toHaveBeenCalledOnce();controls.dispose()
})

it('starts through the desktop lifecycle without a dialog and ignores duplicate or busy starts', async () => {
  document.body.innerHTML = '<button id="menu-presentation-start"></button><dialog id="share-link-dialog"></dialog>'
  const button = document.getElementById('menu-presentation-start'), start = vi.fn(event => {
    expect(event.detail.nativeVR).toBe(true)
    document.getElementById('share-link-dialog').setAttribute('aria-busy', 'true')
  })
  button.addEventListener('click', start)
  const vr = createVRShare({ request: async () => ({ ok: true }) })
  button.disabled = true
  await vr.activate({ sequence: 1, action: 'start' })
  expect(start).not.toHaveBeenCalled()
  button.disabled = false
  await vr.activate({ sequence: 2, action: 'start' })
  await vr.activate({ sequence: 2, action: 'start' })
  await vr.activate({ sequence: 3, action: 'start' })
  expect(start).toHaveBeenCalledOnce()
  expect(vr.state().busy).toBe(true)
})

it('switches an already shared desktop perspective to headset sharing from VR', async () => {
 const onPerspective=vi.fn(),controls=initPresentationControls({onPerspective,onEnd:vi.fn()})
 controls.setActive(true);controls.setPerspective(true);controls.setSource('desktop')
 const vr=createVRShare({request:async()=>({ok:true})})
 await vr.activate({sequence:1,action:'resume'})
 expect(onPerspective).toHaveBeenCalledWith(true,{nativeVR:true})
 controls.dispose()
})
