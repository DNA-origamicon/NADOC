import fs from 'node:fs'
import crypto from 'node:crypto'
import http from 'node:http'
import {expect} from '@playwright/test'


// Import only into the caller's isolated document/workspace; preserve geometry.
export async function importAuditDesign(page, info) {
  const source=process.env.NADOC_VR_AUDIT_DESIGN
  if (!source) return false
  const bytes=fs.readFileSync(source)
  const design=JSON.parse(bytes)
  // New Part hides its welcome/modal before its initial save finishes. Wait
  // for that destination before importing, so its late response cannot assign
  // a different autosave path to the already-imported fixture.
  let workspacePath
  await expect.poll(async()=>{
    workspacePath=await page.evaluate(()=>window.__nadocSyncDebug?.status().workspacePath ?? null)
    return workspacePath
  }, {timeout:10000}).toMatch(/^__e2e__/)
  for (const loadout of design.loadouts||[]) {
    loadout.head_revision_id=null
    loadout.base_revision_id=null
  }
  design.metadata.name='__e2e__24HB audit'
  design.metadata.identity_last_known_path=workspacePath
  await page.evaluate(async content => (await import('/src/api/client.js')).importDesign(content), JSON.stringify(design))
  // Establish the private file's identity before measuring an edit. A synthetic
  // import path different from the browser's autosave path turns a later save
  // into Save As, legitimately clearing Undo and invalidating the VR binding.
  await page.evaluate(async destination => (await import('/src/api/client.js')).saveDesignToWorkspace(destination), design.metadata.identity_last_known_path)
  // Await the public history endpoint rather than comparing lazy UI placeholders.
  await page.evaluate(async()=>{
    const api=await import('/src/api/client.js'),{store}=await import('/src/state/store.js')
    const full=await api._request('GET','/design/feature-log/full')
    store.setState({currentDesign:{...store.getState().currentDesign,feature_log:full.feature_log}})
  })
  const loaded=await page.evaluate(async()=>{
    const s=(await import('/src/state/store.js')).store.getState()
    return {helices:s.currentDesign.helices.length,strands:s.currentDesign.strands.length,nucleotides:s.currentGeometry.length,
      transforms:s.currentDesign.nucleotide_transforms,clusters:s.currentDesign.cluster_transforms}
  })
  expect(loaded.helices).toBe(design.helices.length)
  expect(loaded.strands).toBe(design.strands.length)
  expect(loaded.transforms).toEqual(design.nucleotide_transforms)
  expect(loaded.clusters).toEqual(design.cluster_transforms)
  expect(loaded.nucleotides).toBeGreaterThan(0)
  fs.writeFileSync(info.outputPath('audit-design.json'),JSON.stringify({source,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),...loaded},null,2))
  return true
}

// Bend/Twist must acquire schematic planes before changing representation.
// Their asynchronous probes can request the ordinary desktop style handler
// through this owned loopback bridge without resetting the active tool draft.
export async function startAuditRepresentationBridge(page) {
  if (!process.env.NADOC_VR_AUDIT_DESIGN) return null
  const server=http.createServer(async (request,response)=>{
    try {
      if (request.method!=='POST' || request.url!=='/representation') throw new Error('Unsupported audit request')
      let text=''
      for await (const chunk of request) {
        text+=chunk
        if(text.length>1024) throw new Error('Audit request too large')
      }
      const {representation}=JSON.parse(text)
      if(!['full','stick','ballstick','surface'].includes(representation)) throw new Error('Invalid representation')
      await page.evaluate(representation=>window.__nadocTest.scrywrite.dispatch({
        type:'style',representation,coloring:'strand',
      }),representation)
      response.writeHead(200,{'Content-Type':'application/json'})
      response.end(JSON.stringify({requested:representation}))
    } catch(error) {
      response.writeHead(400,{'Content-Type':'application/json'})
      response.end(JSON.stringify({error:String(error)}))
    }
  })
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve)})
  return {url:`http://127.0.0.1:${server.address().port}/representation`,
    close:()=>new Promise(resolve=>server.close(resolve))}
}

// Optional draw isolation plus read-only frame observations. Neither changes
// focus or visibility; collect in-page while native probes run.
export async function installAuditBrowserTrace(page) {
  if (process.env.NADOC_VR_AUDIT_DESKTOP_DRAW === 'on') {
    await page.addInitScript(() => localStorage.setItem('nadoc:vr-desktop-3d', 'on'))
  }
  if (process.env.NADOC_VR_AUDIT_DESKTOP_DRAW === 'preference-off') {
    await page.addInitScript(() => localStorage.setItem('nadoc:vr-desktop-3d', 'off'))
  }
  // Diagnostic isolation only: suppress draw submission without hiding the
  // document or stopping animation/transaction callbacks. Never changes files
  // served to another browser or production defaults.
  if (process.env.NADOC_VR_AUDIT_DESKTOP_DRAW === 'off') {
    await page.route('**/src/viewer/runtime.js*', async route => {
      const response = await route.fetch()
      const source = await response.text()
      const gate = '(canvas.ownerDocument.hidden || !canvas.ownerDocument.hasFocus())'
      if (source.split(gate).length !== 2) throw new Error('Desktop audit gate changed')
      await route.fulfill({response, body: source.replace(gate, 'true /* isolated desktop-off audit */')})
      // Native probes run synchronously in the test worker. Remove interception
      // before they start, otherwise Chromium's network routing also waits on
      // that worker and stalls unrelated browser feedback requests.
      await page.unroute('**/src/viewer/runtime.js*')
    })
  }
  if (process.env.NADOC_VR_AUDIT_BROWSER_TRACE !== '1') return
  await page.addInitScript(() => {
    window.__vrAuditBrowserTrace = []
    window.__vrAuditRequestTrace = []
    // Measure in Chromium: the worker blocks while the native probe runs, so
    // Playwright request event delivery times cannot measure network latency.
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) {
        if (!/\/api\/(design\/[^?]+|vr\/(?:scene-refresh|end-resize-handles|ligation-ends|tool-execution-feedback|view-tools))(\?|$)/.test(entry.name)) continue
        window.__vrAuditRequestTrace.push({url: entry.name,
          start_ms: performance.timeOrigin + entry.startTime,
          end_ms: performance.timeOrigin + entry.responseEnd, duration_ms: entry.duration})
      }
    }).observe({type: 'resource', buffered: true})
    setInterval(() => {
      const state = window.__nadocTest?.viewerFrameState?.()
      if (!state) return
      const rows = window.__vrAuditBrowserTrace
      rows.push({epoch_ms: Date.now(), native_active: document.querySelector('#menu-help-view-vr')?.getAttribute('aria-pressed') === 'true', ...state})
      if (rows.length > 2400) rows.shift()
    }, 500)
  })
}

export async function saveAuditBrowserTrace(page, info) {
  if (process.env.NADOC_VR_AUDIT_BROWSER_TRACE !== '1') return
  let evidence
  try {
    evidence = {requests: await page.evaluate(() => window.__vrAuditRequestTrace || []),
      samples: await page.evaluate(() => window.__vrAuditBrowserTrace || []),
      condition: '500ms browser frame/focus observations; no focus changes',
      desktop_draw: process.env.NADOC_VR_AUDIT_DESKTOP_DRAW === 'off' ? 'off while native VR active (isolated route)'
        : process.env.NADOC_VR_AUDIT_DESKTOP_DRAW === 'preference-off' ? 'off via Desktop 3D during VR preference' : 'production focus policy'}
  } catch (error) {
    evidence = {error: String(error), samples: []}
  }
  fs.writeFileSync(info.outputPath('browser-frame-trace.json'), JSON.stringify(evidence))
}
