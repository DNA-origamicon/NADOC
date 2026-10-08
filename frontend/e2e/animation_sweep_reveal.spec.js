import { test, expect } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
const DOC = '__e2e__sweep-animation'
const API = `${process.env.NADOC_E2E_API_BASE}/api`
const H = { 'X-NADOC-Doc': DOC }
const evidence = '../.development-artifacts/build-animation/sweep'
// Persistence inventory: File/New autosaves __e2e__-prefixed design/project files;
// global teardown removes both. Isolated backend disables session persistence.
// Screenshots/movie are intentionally retained review evidence outside workspace.
test.afterEach(async ({ page, request }) => { await page.close(); await request.delete(`${API}/documents/${DOC}`) })
test('sweep grows along path and reverses identically in preview and exported video', async ({ page }) => {
  test.setTimeout(120000)
  mkdirSync(evidence, { recursive: true })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(`/?doc=${DOC}`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', DOC)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect.poll(async () => (await page.request.get(`${API}/design`, { headers: H })).status()).toBe(200)
  const sweep = await page.request.post(`${API}/design/sweep`, { headers: H, data: { cells: [[0, 0], [0, 1]], points_nm: [[0, 0, 0], [0, 0, 12], [8, 0, 24], [20, 0, 28]], strand_filter: 'both' } })
  expect(sweep.ok(), await sweep.text()).toBe(true)
  const created = await page.request.post(`${API}/design/animations`, { headers: H, data: { name: 'Sweep reveal', fps: 8 } })
  const d = (await created.json()).design
  const id = d.animations.at(-1).id
  for (const [state, transition, hold] of [[-2, 0, .5], [-1, 4, .5], [-2, 4, .5]]) {
    expect((await page.request.post(`${API}/design/animations/${id}/keyframes`, { headers: H,
      data: { feature_log_index: state, transition_duration_s: transition, hold_duration_s: hold, easing: 'linear' } })).ok()).toBe(true)
  }
  await page.evaluate(doc => { const bc = new BroadcastChannel('nadoc-design'); bc.postMessage({ type: 'design-changed', source: 'e2e-sweep', docId: doc }); bc.close() }, DOC)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.animations?.some(a => a.keyframes.length === 3))
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  if (!await page.locator('#animation-panel-body').isVisible()) await page.locator('#animation-panel-heading').click()
  await page.locator('#animation-select').selectOption(id)
  await page.evaluate(async id => {
    const t = window.__nadocTest
    t.applyCameraPoseForTest({ position: [55, 45, 65], target: [8, 0, 14], up: [0, 1, 0], fov: 40 })
    await t.animPlayer.play(t.store.getState().currentDesign.animations.find(a => a.id === id)); t.animPlayer.pause()
  }, id)
  const samples = []
  for (const [label, time] of [['quarter', 1.5], ['half', 2.5], ['full', 4.5], ['reverseHalf', 7]]) {
    const sample = await page.evaluate(async time => {
      const t = window.__nadocTest; t.animPlayer.seekTo(time); await t.animPlayer.settleFrame()
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      const entries = t.getDesignRenderer().getBackboneEntries()
      const visible = entries.filter(e => { const a = e.instMesh.instanceMatrix.array, i = e.id * 16; return Math.hypot(a[i], a[i+1], a[i+2]) > .0001 }).map(e => e.nuc.bp_index)
      return { min: Math.min(...visible), max: Math.max(...visible), count: visible.length, pixels: t.renderedPixelCensus() }
    }, time)
    samples.push(sample)
    await page.locator('#canvas').screenshot({ path: `${evidence}/${label}.png` })
  }
  expect(samples[0].count).toBeGreaterThan(0)
  expect(samples[0].max).toBeLessThan(samples[1].max)
  expect(samples[1].max).toBeLessThan(samples[2].max)
  expect(samples[0].min).toBe(samples[2].min)
  expect(samples[1]).toEqual(samples[3])
  expect(samples[1].pixels.visible).toBeGreaterThan(100)
  await page.locator('#anim-export-format').selectOption('webm')
  await page.locator('#anim-export-fps').fill('8')
  const download = page.waitForEvent('download')
  await page.locator('#anim-export-btn').click()
  await (await download).saveAs(`${evidence}/sweep.webm`)
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-ss', '2.5', '-i', `${evidence}/sweep.webm`, '-frames:v', '1', `${evidence}/video-half.png`])
  const representations = []
  for (const representation of ['cylinders', 'ballstick', 'surface']) {
    const result = await page.evaluate(async ({ id, representation }) => {
      const t = window.__nadocTest
      await t.setRepresentation(representation)
      await t.animPlayer.play(t.store.getState().currentDesign.animations.find(a => a.id === id)); t.animPlayer.pause()
      const frames = []
      for (const time of [1.5, 2.5, 4.5]) {
        t.animPlayer.seekTo(time); await t.animPlayer.settleFrame()
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        const surface = t.scene.getObjectByName('dna-surface')
        frames.push({ pixels: t.renderedPixelCensus(), surfaceCount: surface?.geometry.drawRange.count })
      }
      t.animPlayer.seekTo(2.5); await t.animPlayer.settleFrame()
      return frames
    }, { id, representation })
    expect(result[0].pixels.visible).toBeGreaterThan(20)
    expect(result[0].pixels.pixelHash).not.toBe(result[2].pixels.pixelHash)
    if (representation === 'surface') {
      expect(result[0].surfaceCount).toBeLessThan(result[1].surfaceCount)
      expect(result[1].surfaceCount).toBeLessThan(result[2].surfaceCount)
    }
    await page.locator('#canvas').screenshot({ path: `${evidence}/${representation}-half.png` })
    representations.push({ representation, frames: result })
    await page.evaluate(() => window.__nadocTest.animPlayer.stop())
  }
  writeFileSync(`${evidence}/samples.json`, JSON.stringify({ samples, representations }, null, 2))
})
