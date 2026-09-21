import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { access, readFile, writeFile, unlink } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'

// Persistent artifacts: :5174 control credential (afterAll), __e2e__ design and
// project history (global teardown). Python uses TemporaryDirectory for its cache.
// Source DCD/PSF/design are read-only; all job HTTP requests are intercepted.
const root = path.resolve(import.meta.dirname, '../..'), controlFile = shareControlFile(path.join(root, 'frontend'), 5174)
let host, ownsControl = false, payload, design
test.beforeAll(async () => {
  test.skip(!existsSync(path.join(root, 'workspace/md_jobs/796c568b5690/design.json')), 'Requires the local read-only cube_pore benchmark job')
  try { await access(controlFile); throw new Error('Test sharing credential already exists') } catch (error) { if (error.code !== 'ENOENT') throw error }
  const python = `
import os,json,tempfile
from pathlib import Path
from threadpoolctl import threadpool_limits
from backend.core.models import Design
from backend.core.md_playback_context import playback_context
from backend.core.md_trajectory import _extract_md_full_frame
p=Path('workspace/md_jobs/796c568b5690/package/cube_pore_namd_solvated')
with tempfile.TemporaryDirectory(prefix='nadoc-trajectory-e2e-') as cache:
 os.environ['NADOC_MD_PLAYBACK_CACHE_DIR']=cache
 with threadpool_limits(limits=1,user_api='blas'):
  c=playback_context(p/'cube_pore.psf',list((p/'output').glob('*.dcd')),p/'cube_pore.pdb',Design.from_json(Path('workspace/md_jobs/796c568b5690/design.json').read_text()))
  try:
   keys=[list(k) for k in c['p_order']]+[list(s[0]) for s in c.get('term_specs',[])]
   print(json.dumps(dict(ready=True,keys=keys,frames=[_extract_md_full_frame(c,i).reshape(-1).tolist() for i in range(0,800,100)],n_frames=8,total_n_frames=8,frame_start=0,frame_format='namd-measured-bases',stages=[],markers=[])))
  finally:c['dcd_prefix'].close()
`
  const result = await promisify(execFile)(path.join(root, '.venv/bin/python'), ['-c', python], { cwd: root, timeout: 60000, maxBuffer: 20 * 1024 * 1024 })
  payload = JSON.parse(result.stdout)
  design = JSON.parse(await readFile(path.join(root, 'workspace/md_jobs/796c568b5690/design.json'), 'utf8'))
  design.id = '__e2e__trajectory_share'; design.metadata.name = '__e2e__trajectory_share'
  host = await createPreparedHost({ dist: path.join(root, 'frontend/dist') })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }), { mode: 0o600 }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(controlFile).catch(() => {}) })

test('one invitation switches real cube_pore from static view to trajectory and back', async ({ page, context }, testInfo) => {
  test.setTimeout(240000)
  const errors = [], logs = []; page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/md/jobs/**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/trajectory-bin')) return route.fulfill({ status: 200, body: Buffer.alloc(0) })
    if (url.pathname.endsWith('/trajectory')) return route.fulfill({ json: payload })
    if (url.pathname.endsWith('/display')) return route.fulfill({ json: { ready: true } })
    return route.fulfill({ json: {} })
  })
  await page.setViewportSize({ width: 800, height: 600 })
  await page.goto('/?doc=__e2e__trajectory_share')
  await page.waitForFunction(() => window.__nadocMdViz && window.__nadocTest)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js'); await api.importDesign(JSON.stringify(design))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const loaded = await window.__nadocMdViz.loadTrajectory('__e2e__trajectory', true, 'lineage', 100, null, { frameStart: 0, frameEnd: 7 })
    if (!loaded.ok) throw new Error(JSON.stringify(loaded))
    window.__nadocTest.applyCameraPoseForTest({ position: [60, 30, 70], target: [0, 0, 0], up: [0, 1, 0], fov: 55 })
  }, design)
  await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
  await page.locator('#menu-help-share-link').evaluate(el => el.click())
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-status]')).toHaveText('Invitation ready. Send it to your guests.', { timeout: 90000 })
  const section = page.locator('#share-link-dialog section').first(), url = await section.locator('input[readonly]').inputValue()
  await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
  const guest = await context.newPage(); await guest.setViewportSize({ width: 800, height: 600 }); guest.on('pageerror', e => errors.push(e.message)); guest.on('console', m => { if (m.text().startsWith('[NADOC_TRAJECTORY_PERF')) logs.push(m.text()) })
  const requests = [], joins = []; guest.on('request', r => { if (r.url().includes('/frame?')) requests.push(r.url()); if (r.url().endsWith('/join')) joins.push(r.url()) })
  await guest.goto(url)
  await expect(guest.locator('#join-submit')).toBeEnabled()
  await guest.locator('#guest-name').fill('Trajectory guest'); await guest.locator('#join-submit').click()
  await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 45000 })
  const originalCookie = (await context.cookies()).filter(c => c.name.startsWith('nadoc_view_')), joinCount = joins.length
  await page.locator('[data-include-clip]').check()
  await page.locator('[data-clip-options] [data-to]').fill('8')
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-status]')).toContainText('Shared view updated', { timeout: 90000 })
  expect(await section.locator('input[readonly]').inputValue()).toBe(url)
  await page.locator('#share-link-dialog').screenshot({ path: testInfo.outputPath('unified-share-controls.png') })
  await expect(guest.locator('[data-trajectory]')).toBeVisible({ timeout: 45000 })
  await expect(guest.locator('[data-progress]')).toContainText('source frame 1 / 8', { timeout: 30000 })
  const first = await guest.locator('canvas').screenshot()
  await section.locator('[data-clip-seek]').evaluate(el => { el.value = '7'; el.dispatchEvent(new Event('change')) })
  await expect(guest.locator('[data-progress]')).toContainText('Paused · source frame 8 / 8')
  const last = await guest.locator('canvas').screenshot()
  expect(first.equals(last)).toBe(false)
  await writeFile(testInfo.outputPath('trajectory-first.png'), first); await writeFile(testInfo.outputPath('trajectory-last.png'), last)
  const cookie = (await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))
  const cdp = await context.newCDPSession(guest)
  await cdp.send('Network.enable'); await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 200, downloadThroughput: 125000, uploadThroughput: 125000 })
  await section.locator('[data-clip-seek]').evaluate(el => { el.value = '0'; el.dispatchEvent(new Event('change')) })
  await section.locator('[data-clip-play]').click()
  await expect(guest.locator('[data-progress]')).toContainText('source frame 8 / 8', { timeout: 30000 })
  await section.locator('[data-clip-pause]').click()
  await expect(guest.locator('[data-progress]')).toContainText('Paused')
  expect((await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))).toEqual(cookie)
  expect(requests.length).toBeLessThan(25)
  await guest.locator('[data-metrics]').click()
  await section.locator('[data-clip-seek]').evaluate(el => { el.value = '3'; el.dispatchEvent(new Event('change')) })
  await expect(guest.locator('[data-progress]')).toContainText('Paused · source frame 4 / 8', { timeout: 30000 })
  await guest.locator('[data-metrics]').click()
  console.log('[trajectory sharing proof]', JSON.stringify({ frameRequests: requests.length, logs }))
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
  await page.locator('[data-include-clip]').uncheck()
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(guest.locator('[data-trajectory]')).toHaveCount(0, { timeout: 45000 })
  await expect(guest.locator('#status')).toContainText('Static snapshot')
  expect(await section.locator('input[readonly]').inputValue()).toBe(url)
  expect(joins.length).toBe(joinCount)
  expect((await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))).toEqual(originalCookie)
  expect(errors).toEqual([])
})
