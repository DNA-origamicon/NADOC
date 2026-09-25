import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { access, readFile, writeFile, unlink, mkdir } from 'node:fs/promises'
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
  // Frozen job snapshots omit external loadout payloads; the disposable copy opens
  // as a standalone design, without the source project's history references.
  design.loadouts = []; design.active_loadout_id = null; design.last_editable_loadout_id = null
  await writeFile(path.join(root, 'workspace/__e2e__trajectory_share.nadoc'), JSON.stringify(design), { flag: 'wx' })
  host = await createPreparedHost({ dist: path.join(root, 'frontend/dist') })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }), { mode: 0o600, flag: 'wx' }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(controlFile).catch(() => {}) })

test('one invitation streams real NAMD frames and returns to the native model', async ({ page, context }) => {
  test.setTimeout(240000)
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  const job = { job_id: '__e2e__trajectory', engine: 'namd', status: 'completed', kind: 'relax', created_at: 1, segments: [], prep_params: {}, viewable: true }
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [job] }))
  await page.route('**/api/md/jobs', route => route.fulfill({ json: [job] }))
  await page.route('**/api/md/jobs/**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/trajectory-bin')) return route.fulfill({ status: 200, body: Buffer.alloc(0) })
    if (url.pathname.endsWith('/trajectory')) return route.fulfill({ json: payload })
    if (url.pathname.endsWith('/display')) return route.fulfill({ json: { ready: true } })
    return route.fulfill({ json: {} })
  })
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/?doc=__e2e__trajectory_share&open=__e2e__trajectory_share.nadoc&open-type=design')
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 60000 })
  await page.waitForFunction(() => window.__nadocMdViz && window.__nadocTest?.store.getState().currentGeometry?.length > 0, null, { timeout: 45000 }).catch(async error => {
    console.log('NAMD boot diagnostic', await page.evaluate(() => ({ design: window.__nadocTest?.store.getState().currentDesign?.metadata, id: window.__nadocTest?.store.getState().currentDesign?.id, error: window.__nadocTest?.store.getState().lastError, text: document.body.innerText.slice(-4000) })), errors)
    throw error
  })
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [60, 30, 70], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }))
  await page.locator('.left-tab-btn[data-tab="dynamics"]').evaluate(el => el.click())
  await page.locator('.engine-selector-btn[data-engine="namd"]').evaluate(el => el.click())
  await page.locator('#simulate-jobs-list [data-job-id="__e2e__trajectory"]').evaluate(el => el.click())
  console.log('NAMD sharing: selected recorded job')
  await page.evaluate(async () => {
    const loaded = await window.__nadocMdViz.loadTrajectory('__e2e__trajectory', true, 'lineage', 100, null, { frameStart: 0, frameEnd: 7 })
    if (!loaded.ok) throw new Error(JSON.stringify(loaded))
    window.__nadocTest.pauseViewerRenderingForTest()
  })
  console.log('NAMD sharing: trajectory loaded')
  await page.locator('#menu-file-sharing').evaluate(el => el.click())
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-copy-link]')).toBeVisible({ timeout: 90000 })
  await page.evaluate(() => { navigator.clipboard.writeText = async value => { window.__copiedShare = value } })
  await page.locator('[data-copy-link]').click()
  const url = await page.evaluate(() => window.__copiedShare)
  await page.locator('#share-link-dialog [data-close]').click()
  const guest = await context.newPage(); await guest.setViewportSize({ width: 800, height: 600 }); guest.on('pageerror', e => errors.push(e.message))
  const frames = [], joins = []
  guest.on('response', r => { if (r.url().includes('/live-frame?') && r.ok()) frames.push(r.url()) })
  guest.on('request', r => { if (r.url().endsWith('/join')) joins.push(r.url()) })
  await guest.goto(url); await expect(guest.locator('#join-submit')).toBeEnabled()
  await guest.locator('#guest-name').fill('Trajectory guest'); await guest.locator('#join-submit').click()
  await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 45000 })
  const originalCookie = (await context.cookies()).filter(c => c.name.startsWith('nadoc_view_')), joinCount = joins.length
  const button = page.locator('[data-share-job="namd"]')
  await button.evaluate(el => el.click()); await expect(button).toHaveText('Stop sharing', { timeout: 90000 })
  await expect.poll(() => frames.length, { timeout: 30000 }).toBeGreaterThan(0)
  const first = await guest.locator('canvas').screenshot(), before = frames.length
  await page.evaluate(() => window.__nadocMdViz.showFrame(7))
  await expect.poll(() => frames.length, { timeout: 30000 }).toBeGreaterThan(before)
  await expect.poll(async () => first.equals(await guest.locator('canvas').screenshot()), { timeout: 30000 }).toBe(false)
  const evidence = path.join(root, 'docs/audits/job_sharing_20260923')
  await mkdir(evidence, { recursive: true })
  const last = await guest.locator('canvas').screenshot({ path: path.join(evidence, 'namd-stream.png') })
  await button.evaluate(el => el.click()); await expect(button).toHaveText('Share', { timeout: 90000 })
  await expect(page.locator('.sharing-job-status')).toContainText('native NADOC model')
  await expect.poll(async () => last.equals(await guest.locator('canvas').screenshot()), { timeout: 45000 }).toBe(false)
  await guest.locator('canvas').screenshot({ path: path.join(evidence, 'namd-native.png') })
  expect(guest.url()).toBe(url); expect(joins.length).toBe(joinCount)
  expect((await context.cookies()).filter(c => c.name.startsWith('nadoc_view_'))).toEqual(originalCookie)
  expect(errors).toEqual([])
})
