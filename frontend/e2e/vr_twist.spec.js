import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs'
import path from 'node:path'

const execute = promisify(execFile)
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
let pid

test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})

test('ScryWrite twist planes, rotation, signed wheel, desktop commit, save and Undo', async ({ page, request }, info) => {
  test.setTimeout(840000)
  await page.goto('/?doc=__e2e__twist-tour&scrywrite=transactions')
  await page.getByRole('button', { name: 'New Part', exact: true }).click()
  await page.getByRole('textbox', { name: 'filename', exact: true }).fill('__e2e__VR Twist')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).toBeHidden()
  // Only fixture creation uses the public API. All measured edits use controllers.
  await page.evaluate(async () => {
    await (await import('/src/api/client.js')).addBundleSegment({ cells: [[0,0],[0,1]], lengthBp: 101 })
  })
  const read = () => page.evaluate(async () => {
    const s = (await import('/src/state/store.js')).store.getState()
    return { design: s.currentDesign, geometry: s.currentGeometry }
  })
  const before = await read()
  fs.writeFileSync(info.outputPath('before.json'), JSON.stringify(before))
  await page.locator('#canvas').click({ position: { x: 30, y: 30 } }); await page.keyboard.press('f')
  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.click('#menu-help-view-vr')
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  const profiles = process.env.NADOC_VR_TWIST_VALIDATE === '1'
    ? ['steady_fast','steady_deliberate','variable_fast','variable_deliberate'] : ['steady_fast']
  const reloadChecks = []
  for (const preset of profiles) {
    const probe = async mode => {
      try {
        const result = await execute('uv', ['run','python','-m','tools.vr_workflows.twist_probe',
          status.scrywrite_socket, info.outputPath(preset, mode), '--preset', preset, '--mode', mode],
        { cwd: path.resolve(process.cwd(),'..'), env: process.env, timeout: 180000, maxBuffer: 4*1024*1024 })
        fs.writeFileSync(info.outputPath(`${preset}-${mode}.log`), result.stdout+result.stderr)
      } catch (error) {
        fs.writeFileSync(info.outputPath(`${preset}-${mode}.log`), (error.stdout||'')+(error.stderr||''))
        throw error
      }
    }
    await probe('edit')
    const saved = await read()
    expect(saved.design.feature_log).toHaveLength(before.design.feature_log.length+1)
    expect(saved.design.feature_log.slice(0,-1)).toEqual(before.design.feature_log)
    expect(saved.design.deformations).toHaveLength((before.design.deformations||[]).length+1)
    expect(saved.geometry).not.toEqual(before.geometry)
    const native = JSON.parse(fs.readFileSync(info.outputPath(preset,'edit/result.json')))
    expect(native.committed_feature_id).toBe(saved.design.feature_log.at(-1).id)
    const operation = saved.design.deformations.at(-1)
    expect(operation.type).toBe('twist')
    expect(operation.params.degrees_per_nm).toBeCloseTo(-1)
    if (await page.locator('#left-tab-toggle').getAttribute('aria-expanded') !== 'true') await page.locator('#left-tab-toggle').click()
    await expect(page.locator('#feature-log-panel')).toContainText('Twist')
    await page.mouse.move(700, 300)
    await page.evaluate(async () => {
      const state = (await import('/src/state/store.js')).store.getState()
      const points = Object.values(state.currentHelixAxes).flatMap(a => a.samples?.length ? a.samples : [a.start,a.end])
      const lo = [0,1,2].map(i => Math.min(...points.map(p => p[i])))
      const hi = [0,1,2].map(i => Math.max(...points.map(p => p[i])))
      const center = lo.map((v,i) => (v+hi[i])/2)
      const distance = Math.max(...lo.map((v,i) => hi[i]-v), 10)*3
      window.__nadocTest.applyCameraPoseForTest({ target: center,
        position: [center[0],center[1]-distance,center[2]], up: [0,0,1] })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    })
    await page.screenshot({ path: info.outputPath(preset,'desktop-twist.png') })
    const filename = saved.design.metadata.identity_last_known_path
    await page.evaluate(async file => (await import('/src/api/client.js')).saveDesignToWorkspace(file), filename)
    const file = path.join(process.env.NADOC_WORKSPACE, filename)
    const onDisk = JSON.parse(fs.readFileSync(file))
    expect(onDisk.deformations).toEqual(saved.design.deformations)
    expect(onDisk.feature_log).toEqual(saved.design.feature_log)
    const artifact = info.outputPath(preset,'twisted.nadoc'); fs.copyFileSync(file, artifact)
    fs.writeFileSync(info.outputPath(preset,'after.json'), JSON.stringify(saved))
    await probe('undo')
    await expect.poll(async () => (await read()).design.deformations).toEqual(before.design.deformations)
    expect((await read()).design.feature_log).toEqual(before.design.feature_log)
    expect((await read()).geometry).toEqual(before.geometry)
    reloadChecks.push({ preset, artifact, saved })
  }
  // A second browser document must not consume the running viewer's event stream.
  await request.post(`${base}/api/vr/stop`)
  for (const { preset, artifact, saved } of reloadChecks) {
    const reload = await page.context().newPage()
    await reload.goto('/?doc=__e2e__twist-reload-'+preset)
    await reload.evaluate(async file => (await import('/src/api/client.js')).loadDesign(file), artifact)
    const restored = await reload.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
    expect(restored.deformations).toEqual(saved.design.deformations)
    expect(restored.feature_log).toEqual(saved.design.feature_log)
    await reload.close()
  }
})
