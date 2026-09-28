import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import path from 'node:path'
const execute = promisify(execFile)
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
let pid
test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})
// Only __e2e__ workspace files; global teardown and the tour's temporary workspace
// clean failures. Hosting transport is intercepted: no links or public service persist.
test('left Share tab controls a desktop-started presenter', async ({ page, request }, info) => {
  test.setTimeout(240000)
  const room = { id: 'test-room', title: '__e2e__VR Share', url: 'https://example.invalid/view', password: 'test', expiresAt: Date.now()+3600000 }
  let active = false; const actions = []
  await page.route('**/__nadoc_share/**', async route => {
    const url = new URL(route.request().url()).pathname
    actions.push(url)
    if (url.endsWith('/create')) { active = true; await route.fulfill({ json: room }) }
    else if (url.endsWith('/stop')) { active = false; await route.fulfill({ json: {} }) }
    else if (url.endsWith('/broadcast/start')) await route.fulfill({ json: { lease: 'test-lease', revision: 'a'.repeat(64) } })
    else await route.fulfill({ json: { running: true, shares: active ? [room] : [], publicAccess: { state: 'ready' }, capabilities: ['share-content-v1','editor-broadcast-v1','view-tools-v1','annotations-v1','selection-ping-v1','sphere-impostors-v1','multi-overlay-v1','hull-cutouts-v1'] } })
  })
  await page.goto(`/?doc=__e2e__share-${process.pid}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new'); await page.fill('#new-design-name','__e2e__VR Share')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await page.evaluate(async () => (await import('/src/api/client.js')).createBundle({cells:[[0,0]],lengthBp:42,plane:'XY',name:'__e2e__Share'}))
  await page.evaluate(() => document.getElementById('menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status=await (await request.get(`${base}/api/vr/status`)).json(); if(status.pid)pid=status.pid
    return status.running && !!status.scrywrite_socket
  },{timeout:30000}).toBe(true)
  async function probe(action) {
    await execute('uv',['run','python','-m','tools.vr_workflows.share_probe',status.scrywrite_socket,info.outputPath(action),action],{cwd:path.resolve(process.cwd(),'..'),env:process.env,timeout:90000})
  }
  await probe('inactive')
  await page.evaluate(() => document.getElementById('menu-file-sharing').click())
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-copy-link]')).toBeVisible()
  await page.locator('#share-link-dialog [data-close]').click()
  const perspective=page.locator('#presentation-controls .presentation-perspective')
  await perspective.click(); await expect(perspective).toHaveAttribute('aria-pressed','true')
  await probe('pause'); await expect(perspective).toHaveAttribute('aria-pressed','false')
  await probe('resume'); await expect(perspective).toHaveAttribute('aria-pressed','true')
  await probe('end'); await expect(page.locator('#presentation-controls')).toBeHidden()
  await probe('ended')
  expect(actions.filter(a=>a.endsWith('/create'))).toHaveLength(1)
  expect(actions.some(a=>a.endsWith('/broadcast/camera'))).toBe(true)
  expect(actions.some(a=>a.endsWith('/broadcast/pause'))).toBe(true)
  await page.screenshot({path:info.outputPath('desktop.png')})
})
