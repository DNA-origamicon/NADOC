import {test,expect} from '@playwright/test'

// Generic graphics only, with a controllable asynchronous representation loader.
// No authored documents, API writes, jobs or downloads. Browser resources die
// with the context; standard reporter/teardown remove reports and bridge keys.
test('Appearance tracing waits for representation geometry and final coordinates',async({page})=>{
  test.setTimeout(180000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/trace-loading-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/trace-loading-check')
  await page.evaluate(async()=>{
    const html=new DOMParser().parseFromString(await(await fetch('/')).text(),'text/html')
    const panel=html.getElementById('photo-settings');panel.disabled=false
    document.body.append(panel)
    const button=Object.assign(document.createElement('button'),{id:'menu-view-atomistic-ballstick',textContent:'Ball & Stick'});document.body.append(button)
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createPhotoMode}=await import('/src/scene/photo_mode.js')
    const {initPhotoPanel}=await import('/src/ui/photo_panel.js')
    const {initRepresentationSwitcher}=await import('/src/ui/representation_switcher.js')
    const {createMockStore}=await import('/src/test-helpers/mock_store.js')
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.1,100);camera.position.z=8
    const renderer=new THREE.WebGLRenderer();renderer.setSize(64,64);document.body.append(renderer.domElement)
    const coarse=new THREE.Mesh(new THREE.SphereGeometry(.8,8,6),new THREE.MeshPhongMaterial({color:0x88ccff}));coarse.name='backboneSpheres';scene.add(coarse)
    let draw=()=>renderer.render(scene,camera),detail=null
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn:fn=>draw=fn,resetRenderFn:()=>draw=()=>renderer.render(scene,camera),setResizeCallback(){},clearResizeCallback(){}})
    const panelUI=initPhotoPanel(mode);mode.activate();panelUI.onEnter();mode.setPathTraceSamples(1)
    const store=createMockStore({currentDesign:{},coloringMode:'strand'})
    let releaseAtoms,releaseCoordinates
    const atoms=new Promise(resolve=>{releaseAtoms=resolve}),coordinates=new Promise(resolve=>{releaseCoordinates=resolve})
    const listener=e=>e.detail.waits.push(coordinates)
    window.addEventListener('nadoc:representation-change',listener)
    const noop=()=>{}
    const switcher=initRepresentationSwitcher({store,api:{},atomisticRenderer:{getMode:()=> 'off'},designRenderer:{setDetailLevel:noop},
      getJointRenderer:()=>null,getSurfaceMode:()=> 'off',applySurfaceMode:noop,
      applyAtomisticMode:async()=>{
        await atoms;coarse.visible=false
        detail=new THREE.Mesh(new THREE.SphereGeometry(.8,24,16),new THREE.MeshPhongMaterial({color:0xff8844}));detail.name='atomSpheres';scene.add(detail)
      },setCGVisible:noop,setColoringMode:noop,reprOptionSliders:noop,getLastDetailLevel:()=>0,setLastDetailLevel:noop,setLodMode:noop,setCurrentRepr:noop})
    const frame=()=>{draw();window.__loadingRAF=requestAnimationFrame(frame)};frame()
    window.__loading={mode,panelUI,switcher,releaseAtoms,releaseCoordinates,
      cleanup(){cancelAnimationFrame(window.__loadingRAF);window.removeEventListener('nadoc:representation-change',listener);switcher.dispose();panelUI.dispose();mode.deactivate();renderer.dispose();for(const m of [coarse,detail]){m?.geometry.dispose();m?.material.dispose()}}}
  })
  await page.locator('#photo-path-tracing').check()
  await expect.poll(()=>page.evaluate(()=>window.__loading.mode.getPathTracingStatus()),{timeout:90000}).toMatchObject({state:'tracing',samples:1,error:''})
  await page.locator('#menu-view-atomistic-ballstick').click()
  await expect.poll(()=>page.evaluate(()=>window.__loading.mode.getPathTracingStatus())).toMatchObject({state:'loading',samples:0})
  await expect(page.locator('#photo-path-status')).toHaveText('0% · Waiting for geometry to finish loading…')
  // Stay idle longer than the old 200 ms debounce, first before geometry and
  // then after meshes arrive but before the job's final coordinates are ready.
  for(const release of [false,true]){
    if(release)await page.evaluate(()=>window.__loading.releaseAtoms())
    const states=await page.evaluate(async()=>{
      const states=[]
      for(let i=0;i<6;i++){await new Promise(r=>setTimeout(r,100));states.push(window.__loading.mode.getPathTracingStatus())}
      return states
    })
    for(const state of states)expect(state).toMatchObject({state:'loading',samples:0,error:''})
  }
  await page.evaluate(()=>window.__loading.releaseCoordinates())
  await expect.poll(()=>page.evaluate(()=>window.__loading.mode.getPathTracingStatus()),{timeout:60000}).toMatchObject({state:'tracing',samples:1,error:''})
  await page.evaluate(()=>window.__loading.cleanup())
  expect(errors).toEqual([])
})
