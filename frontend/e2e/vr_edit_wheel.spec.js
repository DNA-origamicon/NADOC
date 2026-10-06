import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'

test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
let pid

test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})

test('right touchpad wheel Undo and Redo restore document history without menus', async ({ page, request }, info) => {
  test.setTimeout(180000)
  await page.goto('/?doc=__e2e__edit-wheel&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__Edit wheel history')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  const create = name => page.evaluate(async name => (await import('/src/api/client.js')).createBundle({
    cells: [[0,0]], lengthBp: 42, plane: 'XY', name,
  }), name)
  const read = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  await create('__e2e__First bundle')
  const before = await read()
  // Prepare a real history entry through the ordinary desktop API.
  await page.evaluate(async helixId => (await import('/src/api/client.js')).addNick({
    helixId, bpIndex: 20, direction: 'FORWARD',
  }), before.helices[0].id)
  const after = await read()
  expect(after.strands.length).toBeGreaterThan(before.strands.length)
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  for (const action of ['undo', 'redo']) {
    execFileSync('uv', ['run', 'python', '-m', 'tools.vr_workflows.nick_probe',
      status.scrywrite_socket, info.outputPath(action), action], {
      cwd: path.resolve(process.cwd(), '..'), env: process.env, timeout: 60000, stdio: 'inherit',
    })
    const restored = await read()
    expect(restored.strands).toEqual((action === 'undo' ? before : after).strands)
    expect(restored.helices).toEqual((action === 'undo' ? before : after).helices)
    await page.screenshot({ path: info.outputPath(`desktop-${action}.png`) })
  }
})
