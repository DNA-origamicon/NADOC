import { test, expect } from '@playwright/test'
import { readFileSync, writeFileSync, mkdirSync, existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const DOC = '__e2e__animation-build-voltron'
const directory = `${ROOT}workspace/playwright_tests/${DOC}`
const owned = [directory, `${ROOT}workspace/.session/${DOC}`, `${ROOT}workspace/.nadoc-projects/${DOC}`, `${ROOT}workspace/${DOC}.nadoc`]
const evidence = `${ROOT}.development-artifacts/build-animation`
const API = `${process.env.NADOC_E2E_API_BASE}/api`
// Persistence inventory: isolated input, autosave, project and session directories
// are __e2e__ scoped and removed afterEach, including failure. Video and comparison
// frames are deliberate review evidence under .development-artifacts only.
test.beforeAll(() => {
  for (const p of owned) expect(existsSync(p)).toBe(false)
  const design = JSON.parse(readFileSync(`${ROOT}workspace/VoltronCoreArmV2.nadoc`, 'utf8'))
  design.id = DOC; design.metadata.name = DOC
  const keyframe = (id, state, transition, hold) => ({ id, feature_log_index: state,
    transition_duration_s: transition, hold_duration_s: hold, easing: 'linear' })
  design.animations = [{ id: 'build-demo', name: '__e2e__build-demo', fps: 12, loop: false, keyframes: [
    keyframe('initial', -2, 0, 0.5), keyframe('build', 3, 4, 0.5),
    keyframe('reverse', -2, 4, 0.5), keyframe('hold', -2, 1, 0.5),
  ] }]
  mkdirSync(directory, { recursive: true }); mkdirSync(evidence, { recursive: true })
  writeFileSync(`${directory}/${DOC}.nadoc`, JSON.stringify(design))
})
test.afterEach(async ({ page, request }) => {
  try { await page.close(); await request.delete(`${API}/documents/${DOC}`) }
  finally { for (const p of owned) rmSync(p, { recursive: true, force: true }); for (const p of owned) expect(existsSync(p)).toBe(false) }
})

test('Voltron preview traverses intermediate states in both directions and exports timed WebM', async ({ page }) => {
  test.setTimeout(300000)
  await page.setViewportSize({ width: 1920, height: 1080 })
  const errors = [], requests = [], mutations = []
  page.on('console', message => { if (/Could not|animation|NATIVE_PLACEMENT|BUILD_/i.test(message.text())) console.log('BUILD_CONSOLE', message.text()) })
  page.on('pageerror', e => { errors.push(e.message); console.log('BUILD_ERROR', e.message) })
  page.on('request', r => {
    if (r.url().endsWith('/features/geometry-batch')) requests.push(...r.postDataJSON().positions)
    if (r.url().endsWith('/features/seek')) mutations.push(r.url())
  })
  await page.goto(`/?doc=${DOC}&open=${encodeURIComponent(`playwright_tests/${DOC}/${DOC}.nadoc`)}`)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentGeometry?.length > 0, null, { timeout: 90000 })
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  if (!await page.locator('#animation-panel-body').isVisible()) await page.locator('#animation-panel-heading').click()
  await page.locator('#animation-select').selectOption('build-demo')
  await page.evaluate(() => {
    const t = window.__nadocTest, { camera } = t.viewerDiagnostic()
    const play = t.animPlayer.play
    t.animPlayer.play = (...args) => play(...args).catch(error => {
      window.__buildPlayError = error.message
      throw error
    })
    t.applyCameraPoseForTest({ ...camera,
      position: camera.position.map((v, i) => camera.target[i] + (v - camera.target[i]) * 0.5) })
  })
  await page.locator('#anim-playpause-btn').click()
  await page.waitForFunction(() => window.__buildPlayError || document.querySelector('[data-role="animation-preparation"]')?.textContent.includes('Preview ready'), null, { timeout: 120000 })
  expect(await page.evaluate(() => window.__buildPlayError)).toBeUndefined()
  const baseline = await page.evaluate(() => {
    const t = window.__nadocTest; t.animPlayer.pause()
    return { cursor: t.store.getState().currentDesign.feature_log_cursor, design: t.store.getState().currentDesign.id }
  })
  expect(new Set(requests)).toEqual(new Set([-1, -2, 0, 1, 2, 3]))
  const samples = []
  for (const [label, time] of [['initial', 0], ['step0', 1.5], ['step1', 2.5], ['step2', 3.5], ['step3', 4.5], ['reverse2', 6], ['reverse1', 7], ['reverse0', 8], ['hold', 10]]) {
    const sample = await page.evaluate(async time => {
      const t = window.__nadocTest; t.animPlayer.seekTo(time); await t.animPlayer.settleFrame()
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      return { time, pixels: t.renderedPixelCensus(),
        beads: t.viewerDiagnostic().backboneEntries,
        particles: t.scene.getObjectByName('nanoparticles')?.children.length ?? 0 }
    }, time)
    samples.push({ label, ...sample })
    await page.locator('#canvas').screenshot({ path: `${evidence}/preview-${label}.png` })
  }
  console.log('BUILD_PREVIEW', JSON.stringify(samples))
  expect(samples.some(s => s.pixels.visible > 1000)).toBe(true)
  expect(samples[1].pixels.pixelHash).toBe(samples[7].pixels.pixelHash)
  expect(samples[2].pixels.pixelHash).toBe(samples[6].pixels.pixelHash)
  expect(samples[0].pixels.pixelHash).toBe(samples[8].pixels.pixelHash)
  expect(samples[1].pixels.pixelHash).not.toBe(samples[2].pixels.pixelHash)
  expect(mutations).toEqual([])
  expect(samples.every(s => s.particles === 0)).toBe(true)
  expect(samples[0].beads).not.toBe(samples[4].beads)
  await page.locator('#anim-export-format').selectOption('webm')
  await page.locator('#anim-export-fps').fill('12')
  const downloadPromise = page.waitForEvent('download', { timeout: 180000 })
  await page.locator('#anim-export-btn').click()
  const download = await downloadPromise
  const movie = `${evidence}/voltron-build.webm`
  await download.saveAs(movie)
  const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-count_frames', '-show_entries', 'stream=nb_read_frames,width,height:format=duration', '-of', 'json', movie], { encoding: 'utf8' }))
  expect(Number(probe.streams[0].nb_read_frames)).toBe(132)
  expect(Number(probe.format.duration)).toBeCloseTo(11, 2)
  // Decode the actual downloaded video; retained PNGs can be compared to preview.
  for (const [label, time] of [['step0', 1.5], ['step1', 2.5], ['step2', 3.5], ['step3', 4.5], ['reverse2', 6], ['reverse1', 7], ['reverse0', 8], ['hold', 10]]) {
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-ss', String(time), '-i', movie, '-frames:v', '1', `${evidence}/video-${label}.png`])
  }
  expect(await page.evaluate(() => ({ cursor: window.__nadocTest.store.getState().currentDesign.feature_log_cursor, design: window.__nadocTest.store.getState().currentDesign.id }))).toEqual(baseline)
  expect(requests).toHaveLength(6) // Export reuses the exact prepared preview.
  expect(await page.evaluate(() => window.__nadocTest.scene.getObjectByName('nanoparticles')?.children.length)).toBe(1)
  // Exercise the same timestamped encoder through Photo's actual frame session.
  await page.locator('#photo-tab-btn').click()
  await page.locator('#photo-lighting-enabled').check()
  await page.locator('#photo-video-res').selectOption('720p')
  await page.locator('#photo-video-format').selectOption('webm')
  await page.locator('#photo-video-fps').fill('2')
  const photoDownloadPromise = page.waitForEvent('download', { timeout: 180000 })
  await page.locator('#photo-video-btn').click()
  const photoDownload = await photoDownloadPromise
  const photoMovie = `${evidence}/voltron-build-photo.webm`
  await photoDownload.saveAs(photoMovie)
  const photoProbe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-count_frames', '-show_entries', 'stream=nb_read_frames,width,height:format=duration', '-of', 'json', photoMovie], { encoding: 'utf8' }))
  expect(Number(photoProbe.streams[0].nb_read_frames)).toBe(22)
  expect(Number(photoProbe.format.duration)).toBeCloseTo(11, 2)
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-ss', '2.5', '-i', photoMovie, '-frames:v', '1', `${evidence}/photo-step1.png`])
  expect(errors).toEqual([])
  writeFileSync(`${evidence}/video-proof.json`, JSON.stringify({ probe, photoProbe, samples, geometryRequests: requests, errors }, null, 2))
})
