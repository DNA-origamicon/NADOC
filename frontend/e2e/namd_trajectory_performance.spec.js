/** Read-only P5 benchmark. No designs/jobs saved; session persistence disabled by
 * config. All browser artifacts belong to the cleanup reporter's output directory. */
import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const JOB = '594917c0d119'
test('P5 strided atomistic trajectory startup and exact buffered seeks', async ({ page }) => {
  test.skip(!existsSync(fileURLToPath(new URL(`../../workspace/md_jobs/${JOB}/job.json`, import.meta.url))))
  test.setTimeout(240_000)
  const errors = [], requests = new Map()
  page.on('pageerror', e => errors.push(e.message))
  page.on('dialog', d => d.accept())
  page.on('request', r => { if (r.url().includes(`/md/jobs/${JOB}/`)) requests.set(r, Date.now()) })
  page.on('requestfinished', r => {
    if (requests.has(r)) console.log('P5_REQUEST',r.url().split('/').pop(),Date.now()-requests.get(r))
  })
  await page.goto('/?doc=__e2e__namd_trajectory_performance&impostors=1')
  await page.waitForFunction(() => !!window.__nadocTest)
  const welcome = page.locator('#welcome-screen')
  await welcome.locator('.lib-row-name', { hasText: /^24hb_0xT$/ }).first().click()
  await expect(welcome).toHaveClass(/hidden/, { timeout:60_000 })
  await page.waitForFunction(() => window.__nadocTest.viewerDiagnostic().slabEntries > 6000)
  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  await expect.poll(() => page.evaluate(() => {
    let n=0; window.__nadocTest.getAtomisticRenderer().visitAtoms(() => n++); return n
  }), {timeout:120_000}).toBeGreaterThan(100_000)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  const row = page.locator(`#md-jobs-list [data-job-id="${JOB}"]`)
  await row.waitFor({state:'attached',timeout:30_000}); await row.evaluate(el => el.click())
  await expect(page.locator('#md-jobs-traj-toggle')).toBeEnabled({timeout:30_000})
  await page.locator('#md-jobs-traj-interval').evaluate(el => {
    el.value='20'; el.dispatchEvent(new Event('change',{bubbles:true}))
  })
  console.log('P5_WEBGL', await page.evaluate(() => {
    const gl=document.querySelector('canvas').getContext('webgl2')
    const ext=gl.getExtension('WEBGL_debug_renderer_info')
    return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'unknown'
  }))
  if (process.env.NADOC_E2E_COLD_TRAJECTORY === '1') {
    const root=fileURLToPath(new URL('../..',import.meta.url))
    execFileSync(`${root}/.venv/bin/python`, ['-c', `
import os,json
from pathlib import Path
from backend.core.dcd_fast import read_layout
p=Path('workspace/md_jobs/594917c0d119/package/24hb_0xT_namd_solvated')
dcd=p/'output/24hb_0xT_01_production_200ns_k0.dcd'
l=read_layout(dcd)
n=json.loads((p/'charge_audit.json').read_text())['final_solvated']['dna_atoms']
with dcd.open('rb') as f:
 for i in range(0,l.n_frames,20):
  base=l.header_bytes+i*l.frame_bytes+(56 if l.has_cell else 0)
  for axis in range(3):
   off=base+axis*(8+4*l.n_atoms)
   start=off//4096*4096;end=(off+4*n+8191)//4096*4096
   os.posix_fadvise(f.fileno(),start,end-start,os.POSIX_FADV_DONTNEED)
for name in ['24hb_0xT.psf','24hb_0xT.pdb']:
 with (p/name).open('rb') as f:os.posix_fadvise(f.fileno(),0,0,os.POSIX_FADV_DONTNEED)
`], {cwd:root})
    console.log('P5_CACHE advisory eviction immediately before loading')
  }
  const started=Date.now()
  await page.locator('#md-jobs-traj-toggle').check({force:true})
  await page.waitForFunction(() => document.getElementById('md-jobs-traj-status').textContent.includes('buffered'),null,{timeout:90_000,polling:25})
  console.log('P5_SELECTED_TO_BUFFERED_MS',Date.now()-started)
  const slider=page.locator('#md-jobs-traj-slider')
  expect(Number(await slider.getAttribute('max'))).toBe(301)
  const play=page.locator('#md-jobs-traj-play')
  await play.click({force:true})
  await expect.poll(async () => Number(await slider.inputValue()),{timeout:30_000,intervals:[25]}).toBeGreaterThan(0)
  console.log('P5_SELECTED_TO_PLAYING_MS',Date.now()-started)
  const playing=Date.now()
  await expect.poll(async () => Number(await slider.inputValue()),{timeout:45_000,intervals:[100]}).toBeGreaterThan(64)
  console.log('P5_FIRST_64_PLAYBACK_MS',Date.now()-playing)
  await play.click({force:true})
  await slider.evaluate(el => {el.value='249';el.dispatchEvent(new Event('input',{bubbles:true}))})
  await expect(page.locator('#md-jobs-traj-label')).toContainText('250 / 302',{timeout:30_000})
  await expect(page.locator('#md-jobs-traj-status')).toContainText('fully buffered',{timeout:120_000})
  console.log('P5_FULLY_BUFFERED_MS',Date.now()-started)
  const fetched = [...requests.keys()].filter(r=>/frames-atomistic-bin|trajectory-bin/.test(r.url())).length
  const scrubTimes=[]
  for (const index of [0,301,149,2,249,0]) {
    const before=Date.now()
    await slider.evaluate((el,i)=>{el.value=String(i);el.dispatchEvent(new Event('input',{bubbles:true}))},index)
    await expect(page.locator('#md-jobs-traj-label')).toContainText(`${index+1} / 302`)
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
    scrubTimes.push(Date.now()-before)
  }
  console.log('P5_BUFFERED_SCRUB_MS',scrubTimes)
  expect([...requests.keys()].filter(r=>/frames-atomistic-bin|trajectory-bin/.test(r.url())).length).toBe(fetched)
  expect(Math.max(...scrubTimes)).toBeLessThan(500)
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible()),{timeout:20_000}).toBe(true)
  expect(errors).toEqual([])
})
