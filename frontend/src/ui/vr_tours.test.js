import { afterEach, expect, it, vi } from 'vitest'
import { initVrTours } from './vr_tours.js'
let ui
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
afterEach(() => { ui?.dispose(); document.body.innerHTML = ''; vi.restoreAllMocks() })
it('groups tours, switches keyboard tabs, launches selected mode and stops the owned run', async () => {
  document.body.innerHTML = '<button id="menu-debug-vr-tours">VR Tours</button>'
  const data = { groups: [{id:'overview',label:'Overview'}, {id:'right',label:'Right sidebar'}], tours: [
    {id:'all',group:'overview',title:'All tabs',command:'demo',validation_command:'validate',runnable:true},
    {id:'right-properties',group:'right',title:'Properties',command:'properties',validation_command:'properties --validate',runnable:true},
  ] }
  const run = { id:'owned',tour:'right-properties',status:'running',output:'evidence',log:'Starting…' }
  const request = vi.fn(async (url, options) => ({ok:true,json:async () => url.endsWith('/start') ? {run} : url.includes('/stop/') ? {run:{...run,status:'stopping'}} : data}))
  ui = initVrTours({request}); await ui.open()
  document.querySelector('[role=tab]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))
  expect(document.querySelector('[aria-selected=true]').textContent).toBe('Right sidebar')
  const select=document.querySelector('select');select.value='validate';select.dispatchEvent(new Event('change'))
  document.querySelector('[data-start]').click();await flush()
  expect(JSON.parse(request.mock.calls.find(([url])=>url.endsWith('/start'))[1].body)).toEqual({tour:'right-properties',mode:'validate'})
  expect(document.querySelector('[role=status]').textContent).toContain('running')
  expect(document.querySelector('[data-start]').disabled).toBe(true)
  Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Stop tour').click();await flush()
  expect(request.mock.calls.some(([url])=>url==='/api/vr/tours/stop/owned')).toBe(true)
  ui.close();expect(document.querySelector('[role=dialog]')).toBeNull()
})
it('shows launch failures without claiming success', async () => {
  document.body.innerHTML='<button id="menu-debug-vr-tours">VR Tours</button>'
  const request=vi.fn(async url=>({ok:!url.endsWith('/start'),json:async()=>url.endsWith('/start')?{detail:'Close the active VR viewer'}:{groups:[{id:'overview',label:'Overview'}],tours:[{id:'all',group:'overview',title:'All',command:'demo',runnable:true}]}}))
  ui=initVrTours({request});await ui.open();document.querySelector('[data-start]').click();await flush()
  expect(document.querySelector('[role=status]').textContent).toContain('Close the active VR viewer')
  expect(document.querySelector('[data-start]').disabled).toBe(false)
})
