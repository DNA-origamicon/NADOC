// Read-only copied-document check. Browser owns launch and style acknowledgements.
import { chromium } from 'playwright'
import { mkdir, writeFile, readFile, rmdir, copyFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { tmpdir } from 'node:os'
const [doc, directory, source, validation] = process.argv.slice(2)
if (!doc || !directory || !source) throw new Error('Usage: verify-vr-browser.mjs DOC OUTPUT SOURCE [--validate]')
const output = path.resolve(directory)
await mkdir(output, { recursive: true })
const base = process.env.NADOC_BROWSER_BASE || 'http://127.0.0.1:5173'
const api = process.env.NADOC_API_BASE || 'http://127.0.0.1:8000'
const headers = { 'X-NADOC-Doc': doc }
const status = async () => (await fetch(api+'/api/vr/status', { headers })).json()
if ((await status()).running) throw new Error('Close the active viewer before this browser-owned check')
await writeFile(output+'/browser-inventory.txt', 'Isolated copied document; source and session-cache cleanup owned by Python wrapper. No design edits or saves. Temporary Playwright profile removed by browser.close(). Native viewer stopped by matching PID in finally; backend owns its IPC cleanup. Captures/logs stay in this evidence directory.\n')
let browser, page, pid, probe, owned, nativeLog
const requests = [], errors = [], diagnostics = []
try {
  browser = await chromium.launch({ headless: false, args: ['--disable-features=WebXR'] })
  page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  page.on('console', message => {
    if(message.type()==='error') diagnostics.push(message.text())
  })
  page.on('response', async response => {
    try {
      if(response.status()>=400) diagnostics.push(response.url()+' '+response.status()+' '+await response.text())
      if(response.url().includes('/vr/event')) {
        const value=await response.json()
        if(value?.style_sequence) await writeFile(output+'/last-style-event.json',JSON.stringify(value,null,2))
      }
    } catch(error) { if(!page.isClosed()) diagnostics.push(String(error)) }
  })
  page.on('pageerror', e => errors.push(String(e)))
  page.on('request', request => {
    if (request.url().includes('/vr/visualization') && request.method()==='POST') requests.push(request.postDataJSON())
  })
  // Observation adjustment only; preserve production launch and acknowledgement handlers.
  await page.route('**/api/vr/launch', route => route.continue({
    postData: JSON.stringify({...route.request().postDataJSON(), scrywrite_live:"transactions", scrywrite_place_scene_in_view:true}),
  }))
  await page.goto(base+'/?doc='+encodeURIComponent(doc)+'&scrywrite=transactions&open='+encodeURIComponent(source))
  await page.waitForFunction(async expected => {
    const state=(await import('/src/state/store.js')).store.getState()
    return state.currentDesign?.metadata?.name===expected && state.currentGeometry?.length > 0 && document.querySelector('#welcome-screen').classList.contains('hidden')
  }, doc, { timeout: 60000 })
  const before = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  // Production DOM handler: starts the companion AND this page's synchronization.
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  let current
  for (let i=0;i<300;i++) {
    current = await status()
    if (current.running) { pid=current.pid; break }
    await new Promise(resolve=>setTimeout(resolve,100))
  }
  await writeFile(output+'/launch-attempt.json',JSON.stringify(current,null,2))
  if (!pid || !current.scrywrite_socket) throw new Error('Browser launch did not expose ScryWrite')
  await writeFile(output+'/launch.json', JSON.stringify(current,null,2))
  nativeLog=current.log_path
  owned=JSON.parse(await readFile(path.join(tmpdir(), 'nadoc-vr-'+process.getuid()+'.json'), 'utf8'))
  if(owned.pid!==pid) throw new Error('Viewer ownership changed')
  await writeFile(output+'/owned-state.json',JSON.stringify(owned,null,2))
  const args = ['run','python','-m','tools.vr_workflows.browser_representation_probe','--socket',current.scrywrite_socket,'--output',output+'/native']
  if (validation==='--validate') args.push('--validate')
  let log=''
  probe=spawn('uv',args,{cwd:path.resolve('..'),stdio:['ignore','pipe','pipe']})
  probe.stdout.on('data',data=>{log+=data;process.stdout.write(data)})
  probe.stderr.on('data',data=>{log+=data;process.stderr.write(data)})
  const code=await new Promise((resolve,reject)=>{probe.on('error',reject);probe.on('exit',resolve)})
  await writeFile(output+'/probe.log',log)
  if(code!==0) throw new Error('Native/browser probe failed: '+code)
  const results=JSON.parse(await readFile(output+'/native/results.json','utf8'))
  const finalStyle=results.at(-1)
  await page.waitForFunction(id=>document.getElementById(id)?.classList.contains('is-checked'),finalStyle.control)
  await page.screenshot({path:output+'/desktop.png'})
  const after = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  await writeFile(output+'/design-before.json',JSON.stringify(before))
  await writeFile(output+'/design-after.json',JSON.stringify(after))
  if(JSON.stringify(before)!==JSON.stringify(after)) throw new Error('Read-only test changed design')
  if(errors.length) throw new Error('Browser exceptions: '+errors.join('; '))
  await writeFile(output+'/result.json', JSON.stringify({passed:true,desktop:finalStyle.target,errors,acknowledgements:requests.length,designUnchanged:true},null,2))
} finally {
  await page?.screenshot({path:output+'/desktop-final.png'}).catch(()=>{})
  if(probe && probe.exitCode===null) probe.kill('SIGTERM')
  try {
    await writeFile(output+'/browser-errors.json',JSON.stringify(errors,null,2))
    await writeFile(output+'/browser-diagnostics.json',JSON.stringify(diagnostics,null,2))
    await writeFile(output+'/browser-acknowledgements.json',JSON.stringify(requests,null,2))
    if(pid && (await status()).pid===pid) await fetch(api+'/api/vr/stop',{method:'POST',headers})
    for(let i=0;pid && (await status()).pid===pid && i<100;i++) await new Promise(resolve=>setTimeout(resolve,100))
    if(pid && (await status()).pid===pid) throw new Error('Owned viewer did not stop')
  } finally {
    if(nativeLog) await copyFile(nativeLog,output+'/native-viewer.log').catch(error=>diagnostics.push('Could not retain native log: '+error))
    await writeFile(output+'/browser-diagnostics.json',JSON.stringify(diagnostics,null,2))
    await browser?.close()
    if(owned?.scrywrite_socket) {
      try { await rmdir(path.dirname(owned.scrywrite_socket)) }
      catch(error) { if(error.code!=='ENOENT') throw error }
    }
  }
}
