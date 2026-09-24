// Explicit live acceptance check; never discovered by the ordinary unit suite.
// Persists only screenshots/JSON under configured inspector output; context closes
// in finally. No workspace designs, downloads or persistent browser profile.
import {chromium,expect} from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
const root=process.env.INSPECTOR_OUTPUT
if(!root)throw Error('INSPECTOR_OUTPUT required')
const out=path.join(root,'browser');await fs.mkdir(out,{recursive:true})
const browser=await chromium.launch({headless:true})
const context=await browser.newContext({baseURL:'http://127.0.0.1:8766',viewport:{width:1500,height:1100}})
const page=await context.newPage(),errors=[]
page.on('pageerror',e=>errors.push(e.message))
const summary={}
async function captureFrame(){
 const [response]=await Promise.all([
  page.waitForResponse(r=>r.url().endsWith('/api/capture')&&r.request().method()==='POST'),
  page.locator('#capture').click()
 ])
 const frame=await response.json()
 await expect(page.locator('#eyeImage')).toHaveAttribute('src',new RegExp(frame.name+'/'))
 await page.waitForFunction(()=>document.querySelector('#eyeImage').complete&&document.querySelector('#eyeImage').naturalWidth>0)
 return frame.name
}
try {
 await page.goto('http://127.0.0.1:8766')
 await expect(page.locator('#connection')).toContainText('Focused')
 if(!process.env.INSPECTOR_PICK_ONLY)await expect(page.locator('#final')).toBeDisabled()
 if(await page.locator('#visibility').inputValue()!=='normal'){
  await page.locator('#visibility').selectOption('normal')
  await expect(page.locator('#frameInfo')).toContainText('scene normal')
 }
 const capture=await captureFrame()
 await expect(page.locator('#eyeImage')).toBeVisible()
 await page.waitForFunction(()=>document.querySelector('#eyeImage').complete&&document.querySelector('#eyeImage').naturalWidth>0)
 const evidence=JSON.parse(await fs.readFile(path.join(root,capture,'evidence.json')))
 const eye=evidence.eyes[0]
 const ids=await fs.readFile(path.join(root,capture,'left.ids.u32'))
 let index=-1;for(let i=0;i<ids.length;i+=4){
  const p=i/4,x=p%eye.width,y=Math.floor(p/eye.width)
  if(x<9||x>=eye.width-9||y<9||y>=eye.height-9)continue
  const id=ids.readUInt32LE(i)
  if(id>0&&[-8,0,8].every(dy=>[-8,0,8].every(dx=>ids.readUInt32LE(i+(dy*eye.width+dx)*4)===id))){index=p;break}
 }
 if(index<0)throw Error('Normal scene has no identifiable design pixels')
 const nx=(index%eye.width+.5)/eye.width,ny=(eye.height-1-Math.floor(index/eye.width)+.5)/eye.height
 const box=await page.locator('#overlay').boundingBox(),scale=Math.min(box.width/eye.width,box.height/eye.height)
 await page.mouse.click(box.x+(box.width-eye.width*scale)/2+nx*eye.width*scale,box.y+(box.height-eye.height*scale)/2+ny*eye.height*scale)
 await expect(page.locator('#details')).toContainText('identity')
 summary.pixel_pick=JSON.parse(await page.locator('#details').textContent())
 if(summary.pixel_pick.object?.id!==ids.readUInt32LE(index*4))throw Error('Pixel picker did not return the captured design identity')
 await page.locator('#visibility').selectOption('hidden')
 await expect(page.locator('#frameInfo')).toContainText('scene hidden')
 const hidden=(await (await page.request.get('/api/status')).json()).history.at(-1).name
 const hiddenIDs=await fs.readFile(path.join(root,hidden,'left.ids.u32'))
 if(hiddenIDs.some(v=>v!==0))throw Error('Hidden scene retained design pixels')
 summary.hidden_design_ids_zero=true
 if(!process.env.INSPECTOR_PICK_ONLY){
 await page.locator('#initial').click()
 await expect(page.locator('#job')).toContainText('running')
 await expect(page.locator('#capture')).toBeDisabled()
 await expect(page.locator('#job')).toHaveText(/^(passed|failed|error|cancelled)/, {timeout:90000})
 await expect(page.locator('#job')).toHaveText(/^passed/)
 const hiddenState=(await (await page.request.get('/api/status')).json()).state
 await page.locator('#visibility').selectOption('normal')
 await expect(page.locator('#frameInfo')).toContainText('scene normal')
 const normalState=(await (await page.request.get('/api/status')).json()).state
 const shape=s=>({controls:s.controls,cells:s.extrude.visible_cells,scale:s.extrude.menu_scale,radius:s.extrude.lattice_hit_radius_m})
 if(JSON.stringify(shape(hiddenState))!==JSON.stringify(shape(normalState)))throw Error('Scene toggle changed interaction geometry')
 summary.scene_toggle_preserves_geometry=true
 await page.locator('#target').selectOption({label:'EXTRUDE LENGTH WHEEL'})
 await expect(page.locator('#details')).toContainText('hit_half_right')
 await page.locator('#eye').selectOption('right')
 await expect(page.locator('#eyeImage')).toHaveAttribute('src',/right.png/)
 await page.screenshot({path:path.join(out,'inspector-initial.png'),fullPage:true})
 await page.locator('#final').click()
 await expect(page.locator('#job')).toContainText('running')
 await expect(page.locator('#job')).toHaveText(/^(passed|failed|error|cancelled) /,{timeout:180000})
 const completed=await (await page.request.get('/api/status')).json()
 if(completed.job.outcomes.length!==4)throw Error('Final matrix omitted a profile')
 summary.job=completed.job
 await page.locator('#visibility').selectOption('hidden')
 await expect(page.locator('#frameInfo')).toContainText('scene hidden')
 summary.fixture_hidden_after_checks=true
 await captureFrame()
 await page.waitForTimeout(1000)
 await page.locator('#target').selectOption({label:'EXTRUDE LENGTH WHEEL'})
 await page.screenshot({path:path.join(out,'inspector-final.png'),fullPage:true})
 await expect(page.locator('#report')).toBeVisible()
 }
 if(errors.length)throw Error(errors.join('\n'))
 summary.browser_errors=errors;summary.passed=true
 console.log(JSON.stringify(summary,null,2))
} finally {
 await page.screenshot({path:path.join(out,'last-browser-state.png'),fullPage:true})
 await fs.writeFile(path.join(out,process.env.INSPECTOR_PICK_ONLY?'picking-validation.json':'validation.json'),JSON.stringify(summary,null,2)+'\n')
 await context.close();await browser.close()
}
