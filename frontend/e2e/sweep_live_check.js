import {expect} from '@playwright/test'
import {writeFile} from 'node:fs/promises'

/** Exercise the real gizmo while authoritative preview responses are held. */
export async function checkLiveSweep(page,info) {
  let release
  const gate=new Promise(resolve=>{release=resolve})
  const pattern='**/api/design/sweep/preview*'
  let held=0
  await page.route(pattern,async route=>{held++;await gate;await route.continue()})
  const samples=[]
  try {
    const locations=await page.evaluate(()=>window.__nadocTest.getSweepScreenPositions())
    const handle=locations.handles.find(p=>p.name==='X')
    expect(handle).toBeTruthy()
    await page.evaluate(()=>{
      window.__liveAttribute=window.__nadocTest.scene.getObjectByName('sweep-live-cloud').geometry.attributes.position
      window.__liveTimes=[];window.__recordLive=true
      let last=performance.now()
      const frame=now=>{window.__liveTimes.push(now-last);last=now;if(window.__recordLive)requestAnimationFrame(frame)}
      requestAnimationFrame(frame)
    })
    await page.mouse.move(handle.x,handle.y);await page.mouse.down()
    expect(await page.evaluate(()=>window.__nadocTest.controlsEnabled())).toBe(false)
    for(let i=1;i<=12;i++) {
      await page.mouse.move(handle.x+3*i,handle.y)
      samples.push(await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>{
        const scene=window.__nadocTest.scene,path=scene.getObjectByName('sweep-live-path'),cloud=scene.getObjectByName('sweep-live-cloud')
        const a=path.geometry.attributes.position,n=path.geometry.drawRange.count-1,p=scene.getObjectByName('sweep-point-2').position
        resolve({tip:[a.getX(n),a.getY(n),a.getZ(n)],point:p.toArray(),visible:scene.getObjectByName('sweep-live-preview').visible,
          cloudCount:cloud.geometry.drawRange.count,sameBuffer:cloud.geometry.attributes.position===window.__liveAttribute})
      })))) )
    }
    await page.mouse.up()
    expect(await page.evaluate(()=>window.__nadocTest.controlsEnabled())).toBe(true)
    expect(samples.every(s=>s.visible && s.sameBuffer && s.cloudCount>0 && s.cloudCount<=4096)).toBe(true)
    expect(new Set(samples.map(s=>s.tip[0].toFixed(3))).size).toBeGreaterThanOrEqual(10)
    for(const sample of samples)sample.tip.forEach((v,i)=>expect(v).toBeCloseTo(sample.point[i],4))
    await expect(page.locator('#sweep-apply')).toBeDisabled()
    await expect.poll(()=>held).toBeGreaterThan(0)
    expect(await page.evaluate(()=>JSON.stringify(window.__independentRender())===JSON.stringify(window.__independentBefore))).toBe(true)
    await page.screenshot({path:info.outputPath('sweep-live-drag.png')})
    // Changing a direction control also takes effect before the server responds.
    await page.getByRole('checkbox',{name:'Control point orientation'}).check()
    const twist=page.getByRole('spinbutton',{name:'Twist (degrees)'})
    const before=await page.evaluate(()=>window.__nadocTest.scene.getObjectByName('sweep-cross-section-2').quaternion.toArray())
    await twist.fill('45');await twist.blur()
    await expect.poll(()=>page.evaluate(()=>window.__nadocTest.scene.getObjectByName('sweep-cross-section-2').quaternion.toArray())).not.toEqual(before)
    await page.getByRole('checkbox',{name:'Control point orientation'}).uncheck()
    await page.getByRole('spinbutton',{name:'Point X (nm)'}).fill('10')
    const timing=await page.evaluate(()=>{window.__recordLive=false;const a=window.__liveTimes.slice(2).sort((a,b)=>a-b);return {frames:a.length,medianMs:a[Math.floor(a.length*.5)],p95Ms:a[Math.floor(a.length*.95)],maxMs:a.at(-1)}})
    const localUpdate=await page.evaluate(async()=>{
      const {createSweepLivePreview}=await import('/src/scene/sweep_live_preview.js')
      const live=createSweepLivePreview(new window.__nadocTest.scene.constructor())
      live.setBaseline({points_nm:[[0,0,0],[0,0,100]],helix_paths_nm:Array.from({length:128},(_,i)=>Array.from({length:128},(_,j)=>[i%16*2.5,Math.floor(i/16)*2.5,j*100/127]))})
      const times=[]
      for(let i=0;i<70;i++) {
        const begin=performance.now();live.update([[0,0,0],[i/10,0,100]],[])
        if(i>=6)times.push(performance.now()-begin)
      }
      live.dispose();times.sort((a,b)=>a-b)
      return {cloudBudget:4096,updates:times.length,medianMs:times[32],p95Ms:times[60],maxMs:times.at(-1)}
    })
    await writeFile(info.outputPath('sweep-live-timing.json'),JSON.stringify({samples,timing,localUpdate,heldRequests:held},null,2))
  } finally {
    release();await page.unrouteAll({behavior:'wait'})
  }
  await expect(page.locator('#sweep-apply')).toBeEnabled()
}
