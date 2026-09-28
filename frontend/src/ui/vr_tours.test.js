import { afterEach, expect, it, vi } from 'vitest'
import { initVrTours } from './vr_tours.js'
let ui
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
afterEach(() => { ui?.dispose(); document.body.innerHTML = ''; vi.restoreAllMocks() })
const catalog = { groups: [{id:'right',label:'Right sidebar'}], tours: [
  {id:'representations',group:'right',title:'Visualization',description:'Switch the open design',runnable:true},
  {id:'authoring',group:'right',title:'Authoring',description:'Requires an idle viewer',runnable:false},
] }
it('launches directly from nested menus with tooltips and stops only the owned run', async () => {
  document.body.innerHTML = '<div id="menu-debug-vr-tours"></div>'
  const run = { id:'owned',tour:'representations',status:'running',output:'evidence' }
  const request = vi.fn(async url => ({ok:true,json:async () => url.endsWith('/start') ? {run} : url.includes('/stop/') ? {run:{...run,status:'stopping'}} : catalog}))
  ui = initVrTours({request}); await ui.open()
  const group = document.querySelector('[data-category=right]')
  const leaf = group.querySelector('[data-start=representations][data-mode=demo]')
  expect(leaf.textContent).toBe('Visualization demo')
  expect(leaf.title).toBe('Switch the open design')
  expect(document.querySelector('[role=dialog]')).toBeNull()
  expect(group.querySelector('[data-start=authoring]').disabled).toBe(true)
  leaf.click();await flush()
  expect(JSON.parse(request.mock.calls.find(([url])=>url.endsWith('/start'))[1].body)).toEqual({tour:'representations',mode:'demo',assembly_active:false})
  expect(leaf.disabled).toBe(true)
  Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Stop tour').click();await flush()
  expect(request.mock.calls.some(([url])=>url==='/api/vr/tours/stop/owned')).toBe(true)
})
it('reports errors and re-enables launch without opening a popup', async () => {
  document.body.innerHTML='<div id="menu-debug-vr-tours"></div>'
  const toast = vi.fn()
  const request=vi.fn(async url=>({ok:!url.endsWith('/start'),json:async()=>url.endsWith('/start')?{detail:'Open a design'}:catalog}))
  ui=initVrTours({request, showToast:toast});await ui.open();document.querySelector('[data-start]').click();await flush()
  expect(toast).toHaveBeenCalledWith('Open a design',{severity:'error'})
  expect(document.querySelector('[data-start]').disabled).toBe(false)
})
