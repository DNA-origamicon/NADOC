import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initConnectivity } from './connectivity.js'
const particle=(id,x)=>({id,kind:'gold_nanosphere',diameter_nm:10,pose:{values:[1,0,0,x,0,1,0,0,0,0,1,0,0,0,0,1]}})
it('toggles, switches, refreshes and disposes a read-only graph overlay',()=>{
  vi.useFakeTimers();document.body.innerHTML='<button id="menu-help-connectivity"></button>'
  let state={currentDesign:{id:'d',nanoparticles:[particle('a',0),particle('b',50)]}},notify
  const unsubscribe=vi.fn(),store={getState:()=>state,subscribe:cb=>{notify=cb;return unsubscribe}}
  const before=JSON.stringify(state),scene=new THREE.Scene(),controller=initConnectivity({store,scene,setMenuToggle:vi.fn()})
  const menu=document.getElementById('menu-help-connectivity')
  expect(scene.children).toHaveLength(0);menu.click()
  expect(menu.getAttribute('aria-pressed')).toBe('true');expect(scene.children).toHaveLength(1)
  expect(document.querySelectorAll('#connectivity-panel svg path')).toHaveLength(1);expect(JSON.stringify(state)).toBe(before)
  const pathToggle = document.querySelector('[aria-label="Origami pathing preview"]')
  pathToggle.click()
  expect(scene.children).toHaveLength(2)
  expect(scene.children[0].visible).toBe(false)
  expect(scene.children[1].userData.origamiPathPreview).toBe(true)
  const pathDispose = vi.spyOn(scene.children[1].children[0].geometry, 'dispose')
  const size = document.querySelector('[aria-label="Uniform bundle size"]')
  size.value = '12'; size.dispatchEvent(new Event('change'))
  expect(pathDispose).toHaveBeenCalled()
  expect(scene.children[1].userData.hb).toBe(12)
  expect(JSON.stringify(state)).toBe(before)
  pathToggle.click()
  expect(scene.children).toHaveLength(1); expect(scene.children[0].visible).toBe(true)
  const disposed=vi.spyOn(scene.children[0].children[0].geometry,'dispose'),select=document.querySelector('select')
  select.value='1';select.dispatchEvent(new Event('change'));expect(disposed).toHaveBeenCalled();expect(scene.children).toHaveLength(1)
  state={currentDesign:{...state.currentDesign,nanoparticles:[particle('a',0),particle('b',75)]}};notify()
  expect(scene.children).toHaveLength(0);vi.advanceTimersByTime(110);expect(scene.children).toHaveLength(1)
  expect(document.querySelector('.connectivity-stats').textContent).toContain('61 nm')
  document.querySelector('#connectivity-panel button').click();expect(scene.children).toHaveLength(0)
  expect(document.getElementById('connectivity-panel').hidden).toBe(true);expect(menu.getAttribute('aria-pressed')).toBe('false')
  state={currentDesign:null};notify();vi.runAllTimers();menu.click();expect(scene.children).toHaveLength(0)
  expect(document.querySelector('[role="status"]').textContent).toContain('at least two')
  state={...state,assemblyActive:true};notify();vi.runAllTimers();expect(document.querySelector('[role="status"]').textContent).toContain('Open a part')
  controller.dispose();expect(unsubscribe).toHaveBeenCalled();expect(document.getElementById('connectivity-panel')).toBeNull();vi.useRealTimers()
})

it('frames a horizontal nanoparticle layout without moving its points', async () => {
  const { frameConnectivity } = await import('./connectivity.js')
  const { discoverConnectivity } = await import('../design/connectivity_graph.js')
  const sites = [[0,0,0],[60,0,0],[30,0,50]].map((center,i)=>({id:String(i),label:String(i),center,radius:5}))
  const candidate = discoverConnectivity(sites).candidates[0], camera = new THREE.PerspectiveCamera(45,1.5,.1,1000)
  const controls = {target:new THREE.Vector3(),update:()=>camera.updateMatrixWorld()}
  frameConnectivity(candidate, sites, camera, controls)
  for(const site of sites){
    const p=new THREE.Vector3(...site.center).project(camera)
    expect(Math.abs(p.x)).toBeLessThan(.9);expect(Math.abs(p.y)).toBeLessThan(.9);expect(p.z).toBeLessThan(1)
  }
})
