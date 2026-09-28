import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
let pid
test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})
test('radial Nick previews analog scissors and cuts once with wheel Undo and Redo', async ({ page, request }, info) => {
  test.setTimeout(240000)
  await page.goto('/?doc=__e2e__nick&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR Ligation')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.evaluate(async () => (await import('/src/api/client.js')).createBundle({
    cells: [[0,0]], lengthBp: 42, plane: 'XY', name: '__e2e__Ligation',
  }))
  const read = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  const before = await read()
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  let nicked
  for (const action of ['nick','undo','redo']) {
    execFileSync('uv', ['run','python','-m','tools.vr_workflows.nick_probe',status.scrywrite_socket,
      info.outputPath(action),action],{cwd:path.resolve(process.cwd(),'..'),env:process.env,timeout:160000,stdio:'inherit'})
    const after=await read()
    if(action==='nick') {
      expect(after.strands.length).toBe(before.strands.length+1)
      expect(after.feature_log.at(-1).children.filter(c=>c.op_subtype==='nick')).toHaveLength(1)
      nicked=after
    } else if(action==='undo') {
      expect(after.strands).toEqual(before.strands)
    } else {
      expect(after.strands).toEqual(nicked.strands)
    }
    await page.screenshot({path:info.outputPath(`desktop-${action}.png`)})
  }
})
