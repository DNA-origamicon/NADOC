import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Existing source design + PSF/DCD are read-only. No part is created or saved.
// Session cache is disabled by playwright.config; defensive afterEach removes
// this test's session directory. No jobs/project histories are written. The
// isolated Vite credential and all screenshots are removed by global teardown
// and artifact-cleanup-reporter, including failures/timeouts.
const root = fileURLToPath(new URL('../../', import.meta.url))
const doc = '__e2e__zoom-md-atoms'
const source = process.env.NADOC_ZOOM_MD_AUDIT_SOURCE ?? '24hb_2xT.nadoc'
const job = process.env.NADOC_ZOOM_MD_AUDIT_JOB
const session = `${root}workspace/.session/${doc}`
let evidence, original
test.use({ trace: 'off' })

test.beforeAll(() => {
  if (!job) return
  expect(existsSync(session)).toBe(false)
  original = readFileSync(`${root}workspace/${source}`)
  evidence = JSON.parse(execFileSync(`${root}.venv/bin/python`, [
    `${root}frontend/e2e/helpers/zoom_md_payload.py`, `${root}workspace`, source, job,
  ], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 }))
})
test.afterEach(async ({ page, request }) => {
  if (!job) return
  try {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${doc}`)
  } finally {
    rmSync(session, { recursive: true, force: true })
    expect(existsSync(session)).toBe(false)
    expect(readFileSync(`${root}workspace/${source}`).equals(original)).toBe(true)
  }
})

test('saved inset uses real MD atoms and all junction bonds in atomistic and Full main views', async ({ page }, info) => {
  test.skip(!job, 'Opt-in existing PSF/DCD evidence via NADOC_ZOOM_MD_AUDIT_JOB')
  test.setTimeout(180000)
  const errors=[]; page.on('pageerror', e=>errors.push(e.message))
  let socket, mode, index=1
  const sendFrame=()=>socket.send(JSON.stringify({ type:'frame',frame_idx:index,n_frames:2,
    ...(mode==='ballstick' ? {atoms:evidence.frames[index].atoms} : {
      positions:evidence.frames[index].positions,inset_atoms:evidence.frames[index].inset_atoms,
    }) }))
  // Keep software rendering bounded to the inspected region. Coordinates,
  // identities and connectivity are the real native response, unmodified.
  await page.route(/\/api\/design\/atomistic(?:\?|$)/,async route=>{
    const response=await route.fetch(), data=await response.json(), keys=new Set(evidence.keys)
    data.atoms=data.atoms.filter(a=>keys.has(a.crossover_id!=null
      ? `__xb__:${a.crossover_id}:${a.extra_base_k}`
      : `${a.helix_id}:${a.bp_index}:${a.direction}${a.copy_k?':'+a.copy_k:''}`))
    const serials=new Set(data.atoms.map(a=>a.serial))
    data.bonds=data.bonds.filter(([a,b])=>serials.has(a)&&serials.has(b))
    await route.fulfill({response,json:data})
  })
  // Replay only the read-only display transport; real source positions and PSF
  // edges above exercise the actual MD controller, renderers and inset frame loop.
  await page.routeWebSocket('**/ws/md-run', ws=>{
    socket=ws
    ws.onMessage(raw=>{
      const msg=JSON.parse(raw)
      if(msg.action==='load') {
        mode=msg.mode
        ws.send(JSON.stringify({type:'ready',n_frames:2,n_p_atoms:evidence.keys.length,atom_bonds:evidence.bonds.flat()}))
      } else if(['get_latest','seek'].includes(msg.action)) sendFrame()
    })
  })
  await page.setViewportSize({width:1400,height:1000})
  await page.goto(`/?debug=1&doc=${doc}`)
  await page.waitForFunction(()=>window.__nadocTest && window.__nadocMdDisplay && window.__NADOC_ZOOM_VOLUME__)
  await page.evaluate(async source=>{
    const api=await import('/src/api/client.js')
    await api.loadDesign(source)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  },`${root}workspace/${source}`)
  await expect.poll(()=>page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.debug().ready),{timeout:60000}).toBe(true)
  await expect(page.locator('.zoom-volume-row [data-control="status"]')).toContainText('1 attachment bases included')
  const native=await page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.debugAtoms())
  expect(native.length).toBe(evidence.frames[0].atoms.length)
  await page.evaluate(()=>window.__nadocTest.setRepresentation('ballstick'))
  await page.waitForFunction(()=>window.__nadocTest.getAtomisticRenderer().getMode()==='ballstick')
  await page.evaluate(job=>window.__nadocMdDisplay.displayLatest('audit-existing-p1.conf',{jobId:job,live:false}),job)
  const audit=async()=>page.evaluate(async expected=>{
    const {canonicalAtomName}=await import('/src/scene/md_inset_atoms.js')
    const map=new Map(expected.atoms.map(a=>[`${a.base_key}:${canonicalAtomName(a.name)}`,[a.x,a.y,a.z]]))
    const atoms=window.__NADOC_ZOOM_VOLUME__.debugAtoms(), actual=new Map(atoms)
    let error=0,missing=0
    for(const [k,p] of map){const q=actual.get(k);if(!q)missing++;else error=Math.max(error,Math.hypot(...p.map((v,i)=>v-q[i])))}
    const bySerial=new Map(expected.atoms.map(a=>[a.serial,`${a.base_key}:${canonicalAtomName(a.name)}`]))
    let maxBond=0
    for(const [a,b] of expected.bonds){const p=actual.get(bySerial.get(a)),q=actual.get(bySerial.get(b));if(p&&q)maxBond=Math.max(maxBond,Math.hypot(...p.map((v,i)=>v-q[i])))}
    return {count:atoms.length,missing,error,maxBond,bounds:window.__NADOC_ZOOM_VOLUME__.debug().bounds,
      coarseCount:window.__nadocTest.getDesignRenderer().getFemPositions()?.length??0}
  },{...evidence.frames[index],bonds:evidence.bonds})
  await expect.poll(async()=>(await audit()).error,{timeout:30000}).toBeLessThan(1e-4)
  let result=await audit()
  expect(result.missing).toBe(0);expect(result.coarseCount).toBe(0);expect(result.maxBond).toBeLessThan(.22)
  expect(result.count).toBe(evidence.frames[index].atoms.length)
  index=0;sendFrame()
  await expect.poll(async()=>(await audit()).error).toBeLessThan(1e-4)
  await page.evaluate(()=>window.__nadocTest.setRepresentation('full'))
  await expect.poll(()=>mode).toBe('nadoc')
  await expect.poll(async()=>(await audit()).error).toBeLessThan(1e-4)
  await expect.poll(async()=>(await audit()).coarseCount).toBeGreaterThan(0)
  index=1;sendFrame()
  await expect.poll(async()=>(await audit()).error).toBeLessThan(1e-4)
  result=await audit();expect(result.missing).toBe(0);expect(result.maxBond).toBeLessThan(.22)
  const inset=page.locator('.zoom-volume-inset')
  await expect(inset).toBeVisible()
  await inset.screenshot({path:info.outputPath('p1-inset.png')})
  console.log('INSET_REVIEW',info.outputPath('p1-inset.png'))
  console.log('INSET_AUDIT',JSON.stringify({...result,bonds:evidence.bonds.length,sourceFrames:evidence.frames.map(f=>f.source_frame)}))
  if(process.env.NADOC_ZOOM_REVIEW_HOLD_MS) await page.waitForTimeout(Number(process.env.NADOC_ZOOM_REVIEW_HOLD_MS))
  await page.evaluate(()=>window.__nadocMdDisplay.stopAndRestore())
  await expect.poll(()=>page.evaluate(()=>window.__NADOC_ZOOM_VOLUME__.debug().ready)).toBe(true)
  await expect.poll(()=>page.evaluate(expected=>{
    const actual=new Map(window.__NADOC_ZOOM_VOLUME__.debugAtoms())
    return Math.max(...expected.map(([k,p])=>{const q=actual.get(k);return q?Math.hypot(...p.map((v,i)=>v-q[i])):Infinity}))
  },native)).toBeLessThan(1e-4)
  expect(errors).toEqual([])
})
