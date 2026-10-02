import {installAuditBrowserTrace, saveAuditBrowserTrace} from './helpers/vr_audit_design.js'
import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs'
import crypto from 'node:crypto'
import path from 'node:path'
const execute = promisify(execFile)
const base = process.env.NADOC_E2E_API_BASE
const physical = !!process.env.NADOC_PHYSICAL_VR_TEST
let pid
// Artifact inventory: the launcher provides a temporary NADOC_WORKSPACE containing
// private design/job/cache copies. Only immutable DCD/XTC/TRR inputs are symlinked.
// The launcher removes the entire workspace in finally; afterEach stops our viewer.
// Stereo, browser and controller evidence stays in the configured output directory.
test.afterEach(async ({ request }) => {
  if (!pid) return
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (status.pid === pid) await request.post(`${base}/api/vr/stop`)
  pid = null
})
test(`${process.env.NADOC_VR_AUDIT_DESIGN ? path.basename(process.env.NADOC_VR_AUDIT_DESIGN, '.nadoc') : '2hb_1xT'} simulation jobs activate static results through VR controls`, async ({ page, request }, info) => {
  test.skip(!physical, 'Launch using Debug → VR Tours & Tests → Simulation results')
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const coverage = []
  const deliveryFailures = []
  // Optional diagnostic campaign: sample engine navigation across motion profiles.
  // The discoverable demo/validation defaults still cover every available mode.
  const modeLimit = Number(process.env.NADOC_VR_SIM_MODE_LIMIT || Infinity)
  let snapshot
  page.on('request', request => {
    if (request.url().endsWith('/api/vr/simulations')) snapshot = request.postDataJSON()
  })
  const doc = `__e2e__simulations-${process.pid}`
  if (process.env.NADOC_VR_FRAME_AUDIT === '1') { const cdp = await page.context().newCDPSession(page); await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: false }) }
  await page.goto(`/?doc=${doc}&scrywrite=transactions`)
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator(`[data-library-path="${process.env.NADOC_VR_AUDIT_DESIGN?path.basename(process.env.NADOC_VR_AUDIT_DESIGN):'2hb_1xT.nadoc'}"]`).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 30000 })
  if(process.env.NADOC_VR_AUDIT_DESIGN) {
    const sourceBytes=fs.readFileSync(process.env.NADOC_VR_AUDIT_DESIGN)
    const source=JSON.parse(sourceBytes)
    const loaded=await page.evaluate(async()=>{const s=(await import('/src/state/store.js')).store.getState();return {helices:s.currentDesign.helices.length,strands:s.currentDesign.strands.length,nucleotides:s.currentGeometry.length}})
    expect(loaded.helices).toBe(source.helices.length)
    expect(loaded.strands).toBe(source.strands.length)
    fs.writeFileSync(info.outputPath('audit-design.json'),JSON.stringify({source:process.env.NADOC_VR_AUDIT_DESIGN,sha256:crypto.createHash('sha256').update(sourceBytes).digest('hex'),...loaded}))
  }
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  if(process.env.NADOC_VR_AUDIT_DESIGN)await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await expect(page.locator('#simulate-jobs-list [data-job-id]').first()).toBeVisible()
  await page.evaluate(() => document.getElementById('menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 60000 }).toBe(true)
  await expect.poll(() => snapshot?.engines.length, { timeout: 30000 }).toBe(5)
  let step = 0
  async function probe(id) {
    const output = info.outputPath(`${step++}-${id.replaceAll(':', '-')}`)
    await execute('uv', ['run', 'python', '-m', 'tools.vr_workflows.simulation_probe', status.scrywrite_socket, output, id], {
      cwd: path.resolve(process.cwd(), '..'), env: process.env, timeout: 120000, maxBuffer: 10 * 1024 * 1024,
    })
    if (id === 'capture') {
      const delivery = JSON.parse(fs.readFileSync(path.join(output, 'delivery.json'), 'utf8'))
      if (!delivery.passed) deliveryFailures.push({ output, ...delivery })
    }
  }
  await probe('setup')
  for (const engine of (process.env.NADOC_VR_SIM_ENGINES || 'cando,snupi,mrdna,oxdna,namd').split(',')) {
    await probe(`e:${engine}`)
    await expect.poll(() => snapshot?.engine).toBe(engine)
    await expect.poll(() => snapshot?.jobs.length ?? 0).toBeGreaterThan(0)
    const jobIds = [...snapshot.jobs].filter(row => !row.id.endsWith(':tree')).map(row => row.id)
    const seen = new Set()
    for (const job of jobIds) {
      await probe(job)
      await expect.poll(() => snapshot?.selected).toBeTruthy()
      await page.waitForTimeout(700)
      const modes = await page.evaluate(async engine => (await import('/src/scene/vr_simulations.js')).simulationControls(document, engine)
        .filter(c => c.element.type === 'radio' && c.element.value !== 'off' && /display-mode|(?:md|oxdna)-viz/.test(c.element.name))
        .map(c => ({ id: c.id, label: c.label, mode: c.element.value, enabled: c.enabled })), engine)
      fs.appendFileSync(info.outputPath('availability.jsonl'), JSON.stringify({ engine, job: snapshot.selected, modes }) + '\n')
      for (const mode of modes) {
        if (!mode.enabled || seen.has(mode.mode)) continue
        await probe(mode.id)
        await expect.poll(async () => page.evaluate(async ({ engine, id }) => (await import('/src/scene/vr_simulations.js')).simulationControls(document, engine).find(c => c.id === id)?.active, { engine, id: mode.id })).toBe(true)
        // The actual mesh feed must contain the static result, not just a checked radio.
        await expect.poll(async () => {
          const text = await execute('uv', ['run', 'python', '-c',
            'import json,sys;from frontend.scrywrite.mcp_bridge import Bridge;print(json.dumps(Bridge(sys.argv[1]).call("scrywrite_observe",{})))', status.scrywrite_socket], { cwd: path.resolve(process.cwd(), '..'), env: process.env })
          const state = JSON.parse(text.stdout)
          return !!(state.view_tools.flags & 2048) && (state.view_tools.instances + state.view_tools.triangles + state.view_tools.lines > 0)
        }, { timeout: 120000, intervals: [500, 1000] }).toBe(true)
        await probe('capture')
        coverage.push({ engine, job: snapshot.selected, ...mode })
        fs.writeFileSync(info.outputPath('coverage.json'), JSON.stringify(coverage, null, 2))
        await page.screenshot({ path: info.outputPath(`${engine}-${mode.mode}.png`) })
        const off = await page.evaluate(async engine => (await import('/src/scene/vr_simulations.js')).simulationControls(document, engine).find(c => c.element.type === 'radio' && c.element.value === 'off')?.id, engine)
        if (off) await probe(off)
        seen.add(mode.mode)
        if (seen.size >= modeLimit) break
      }
      if (seen.size >= modeLimit || modes.every(m => seen.has(m.mode))) break
    }
    expect(coverage.some(row => row.engine === engine), `${engine} has no activated result`).toBe(true)
  }
  expect(errors).toEqual([])
  expect(deliveryFailures, 'Desktop delivery checks failed; stereo and per-mode evidence retained').toEqual([])
})

// Optional read-only resource-condition evidence for full-size VR audits.
test.beforeEach(async ({page}) => { await installAuditBrowserTrace(page) })
test.afterEach(async ({page}, info) => { await saveAuditBrowserTrace(page, info) })
