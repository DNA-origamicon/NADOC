import { test, expect } from '@playwright/test'
import { execFileSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { makeVRJoinFixture, importVRJoinFixture } from './helpers/vr_join_fixture.js'

test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')

// Inventory: __e2e__ parts/.nadoc-projects → global teardown; session cache disabled.
// Owned native sidecars/captures → finally stop + private runner TMPDIR cleanup.
// Isolated Vite credential → global teardown. All retained JSON/stereo/frame logs
// use testInfo.outputPath on Archive; no user design or running viewer is used.
test('physical VR Join selects, moves, rotates, snaps wheels, cancels, applies and undoes', async ({ page, request }, info) => {
  test.setTimeout(300_000)
  const base = process.env.NADOC_E2E_API_BASE
  const root = path.resolve(import.meta.dirname, '../..')
  let ownedPid, status, sampler, samplerLog, samplerError
  const stopOwnedViewer = async () => {
    if (!ownedPid) return
    // Node's request survives an interrupted Playwright browser/request fixture.
    const current = await (await fetch(`${base}/api/vr/status`, { signal: AbortSignal.timeout(10_000) })).json()
    if (current.pid === ownedPid) await fetch(`${base}/api/vr/stop`, { method: 'POST', signal: AbortSignal.timeout(10_000) })
    // /vr/stop acknowledges the signal immediately. Await actual exit so the
    // native trace writer drains its final record before copying retained logs.
    const deadline = Date.now() + 10_000
    while (fs.existsSync(`/proc/${ownedPid}`) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50))
    if (fs.existsSync(`/proc/${ownedPid}`)) throw new Error('Owned Join viewer did not finish shutdown')
  }
  try {
    const fixture = makeVRJoinFixture()
    await importVRJoinFixture(page, { design: fixture.posed }, '__e2e__vr-join-physical', { physical: true })
    const read = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
    const before = await read()
    fs.writeFileSync(info.outputPath('before.json'), JSON.stringify(before))
    await page.locator('#canvas').click({ position: { x: 30, y: 30 } })
    await page.keyboard.press('f')
    await page.getByRole('button', { name: 'Help', exact: true }).hover()
    await page.locator('#menu-help-view-vr').click()
    await expect.poll(async () => {
      status = await (await request.get(`${base}/api/vr/status`)).json()
      if (status.pid) ownedPid = status.pid
      return status.running && !!status.scrywrite_socket
    }, { timeout: 60_000 }).toBe(true)
    samplerLog = fs.openSync(info.outputPath('compositor.log'), 'w')
    sampler = spawn('uv', ['run', '--with', 'openvr', 'python', '-m', 'tools.vr_workflows.compositor_timing',
      '--output', info.outputPath('compositor.jsonl'), '--seconds', '300'],
    { cwd: root, env: process.env, detached: true, stdio: ['ignore', samplerLog, samplerLog] })
    sampler.on('error', error => { samplerError = String(error) })
    const samplerDeadline = Date.now() + 20_000
    while (!fs.existsSync(info.outputPath('compositor.jsonl')) && !samplerError && sampler.exitCode == null && Date.now() < samplerDeadline)
      await new Promise(resolve => setTimeout(resolve, 100))
    const probe = stage => execFileSync(path.join(root, '.venv/bin/python'), ['-m', 'tools.vr_workflows.join_probe',
      status.scrywrite_socket, info.outputPath(stage), info.outputPath('before.json'), stage],
    { cwd: root, env: process.env, stdio: 'inherit', timeout: 180_000 })
    probe('cancel')
    expect((await read()).cluster_transforms).toEqual(before.cluster_transforms)
    expect((await read()).strands).toEqual(before.strands)
    probe('apply')
    await expect.poll(async () => (await read()).strands.filter(s => s.strand_type === 'scaffold').length).toBe(1)
    const after = await read()
    expect(after.feature_log.at(-1).op_kind).toBe('cluster-join')
    expect(after.strands.filter(s => s.strand_type === 'staple')).toEqual(before.strands.filter(s => s.strand_type === 'staple'))
    await page.screenshot({ path: info.outputPath('desktop-applied.png') })
    probe('undo')
    await expect.poll(async () => (await read()).strands).toEqual(before.strands)
    expect((await read()).cluster_transforms).toEqual(before.cluster_transforms)
    fs.writeFileSync(info.outputPath('result.json'), JSON.stringify({ applied: after, undo_restored: true }))
  } finally {
    try {
      if (sampler?.pid && sampler.exitCode == null && sampler.signalCode == null) {
        const exited = new Promise(resolve => sampler.once('exit', resolve))
        try { process.kill(-sampler.pid, 'SIGTERM') } catch {}
        await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 5000))])
        if (sampler.exitCode == null && sampler.signalCode == null) {
          try { process.kill(-sampler.pid, 'SIGKILL') } catch {}
          await exited
        }
      }
      if (samplerLog != null) fs.closeSync(samplerLog)
      fs.writeFileSync(info.outputPath('compositor-status.json'), JSON.stringify({
        started: !!sampler?.pid, exitCode: sampler?.exitCode, signal: sampler?.signalCode,
        error: samplerError ?? null, data: fs.existsSync(info.outputPath('compositor.jsonl')),
      }))
    } finally {
      await stopOwnedViewer()
      if (status?.log_path && fs.existsSync(status.log_path)) {
        fs.copyFileSync(status.log_path, info.outputPath('viewer.log'))
      }
    }
  }
})
