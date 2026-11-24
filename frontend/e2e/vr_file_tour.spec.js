import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
const execute = promisify(execFile)
const base = process.env.NADOC_E2E_API_BASE
const headers = { 'X-NADOC-Doc': '__e2e__vr-file-tour' }
let pid
// Artifact inventory: the runner owns a temporary workspace containing one empty
// folder. No saved parts/assemblies. Captures/logs are under the evidence/output
// directory. afterEach stops only our viewer; global teardown removes credentials;
// runner verifies no structure files and removes its temporary workspace on failure.
test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`, { headers })).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`, { headers })
})
test('File demo visibly types and cancels New Part, browses folders, and closes the session', async ({ page, request }) => {
  test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
  const out = process.env.NADOC_VR_FILE_EVIDENCE
  const seed = await request.post(`${base}/api/design`, { headers, data: { name: '__e2e__Empty VR runtime', lattice_type: 'HONEYCOMB' } })
  expect(seed.ok()).toBe(true)
  const launch = await request.post(`${base}/api/vr/launch`, { headers, data: { scrywrite_live: 'transactions' }, timeout: 300_000 })
  expect(launch.ok(), await launch.text()).toBe(true)
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`, { headers })).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30_000 }).toBe(true)
  const wires = [], errors = []
  page.on('request', r => { if (r.url().endsWith('/api/vr/routing')) wires.push(r.postDataJSON()) })
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?test=1&doc=__e2e__vr-file-tour&scrywrite=transactions')
  await expect.poll(() => wires.at(-1)?.roots.some(r => r.id === 'file-new')).toBe(true)
  expect(await page.evaluate(() => import('/src/state/store.js').then(({store}) => store.getState().currentDesign))).toBeNull()
  try {
    const probe = execute(path.resolve('..', '.venv/bin/python'), ['-m', 'tools.vr_workflows.file_probe', status.scrywrite_socket, out],
      { cwd: path.resolve('..'), env: process.env, timeout: 540_000, maxBuffer: 4*1024*1024 })
    probe.child.stdout.on('data', chunk => process.stdout.write(chunk))
    probe.child.stderr.on('data', chunk => process.stderr.write(chunk))
    await probe
    await expect.poll(async () => (await (await request.get(`${base}/api/vr/status`, { headers })).json()).running).toBe(false)
    expect(wires.some(w => w.title === 'Filename keyboard' && w.controls.some(c => c.id === 'info-filename' && c.label === 'demo2'))).toBe(true)
    expect(await page.evaluate(() => import('/src/state/store.js').then(({store}) => store.getState().currentDesign))).toBeNull()
    expect(errors).toEqual([])
  } finally {
    writeFileSync(path.join(out, 'browser.json'), JSON.stringify({ errors, wires }, null, 2))
  }
})
