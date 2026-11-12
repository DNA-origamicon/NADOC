import { test, expect } from '@playwright/test'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Reads an existing example; browser-only animation edits, no structure authoring.
// Download lives in testInfo.outputPath, removed by artifact-cleanup-reporter on
// success/failure. Offline context closes in finally. Session persistence is disabled.
test('compiles sidebar keyframes and plays the downloaded presentation without networking', async ({ page, browser }, testInfo) => {
  test.setTimeout(120000)
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=__e2e__compiled-presentation')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async example => {
    const api = await import('/src/api/client.js'); await api.loadDesign(example)
  }, path.resolve(import.meta.dirname, '..', '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.waitForFunction(() => !!window.__nadocTest.store.getState().currentDesign?.id)
  await page.evaluate(() => {
    const { store } = window.__nadocTest, design = store.getState().currentDesign
    store.setState({ currentDesign: { ...design, animations: [{ id: 'compile-test', name: 'Offline talk', fps: 10,
      keyframes: [1, 2].map(id => ({ id: String(id), text: `Keyframe ${id}`, transition_duration_s: 0.1, hold_duration_s: 0.3 })) }] } })
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel').classList.remove('locked-hidden')
    for (const button of document.querySelectorAll('#left-tab-strip button')) button.disabled = false
    window.__leftSidebar.refresh()
  })
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  const animationScrub = await page.locator('#anim-scrub').boundingBox()
  const animationPlay = await page.locator('#anim-playpause-btn').boundingBox()
  expect(animationPlay.y).toBeGreaterThanOrEqual(animationScrub.y + animationScrub.height)
  const compile = page.locator('#anim-compile-presentation-btn')
  await expect(compile).toBeEnabled()
  await expect(compile).toHaveText('Pre-compile')
  await expect(compile.locator('svg')).toHaveCount(1)
  const load = page.locator('#tab-content-scene .compile-open')
  await expect(load).toHaveText('Load')
  const a = await compile.boundingBox(), b = await load.boundingBox()
  expect(Math.abs(a.y - b.y)).toBeLessThan(1)
  expect(Math.abs(a.height - b.height)).toBeLessThan(1)
  expect(b.x - a.x - a.width).toBeCloseTo(8, 0)
  expect(await compile.evaluate(el => el.closest('.animation-compile').previousElementSibling.id)).toBe('anim-start-presentation-btn')
  const sizeControl = page.getByLabel('Compiled video size')
  await expect(sizeControl).toHaveCSS('color-scheme', 'dark')
  await expect(sizeControl).toHaveCSS('border-radius', '4px')
  expect(await sizeControl.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe('rgb(255, 255, 255)')
  await sizeControl.selectOption('720p')
  await compile.click()
  await expect(page.locator('#tab-content-scene .compile-summary')).toHaveText(/Ready|Compilation failed|cancelled/, { timeout: 90000 })
  await expect(page.locator('#tab-content-scene .compile-summary')).toContainText('Ready')
  // In-app handoff preserves the paused clip, permits real orbit/zoom, then
  // restores the authored viewpoint when inspecting that clip again.
  await page.locator('#tab-content-scene').getByRole('button', { name: 'Play compiled', exact: true }).click()
  const embedded = page.frameLocator('iframe[title="Compiled presentation"]')
  await embedded.locator('#replay').click()
  await expect(embedded.locator('video')).toBeVisible()
  await embedded.locator('video').evaluate(async video => {
    video.pause()
    if (video.currentTime !== 0.2) {
      const ready = new Promise(resolve => video.addEventListener('seeked', resolve, { once: true }))
      video.currentTime = 0.2; await ready
    }
  })
  // An unavailable live frame must leave the paused video and its controls usable.
  await page.evaluate(() => {
    const player = window.__nadocTest.animPlayer
    window.__originalCompiledSettle = player.settleFrame
    player.settleFrame = async () => false
  })
  await page.getByRole('button', { name: 'Inspect in 3D', exact: true }).click()
  await expect(page.locator('.compiled-app-toolbar [role="status"]')).toContainText('not ready')
  await expect(embedded.locator('video')).toBeVisible()
  await page.evaluate(() => {
    window.__nadocTest.animPlayer.settleFrame = window.__originalCompiledSettle
    delete window.__originalCompiledSettle
  })
  await page.getByRole('button', { name: 'Inspect in 3D', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Return to presentation', exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.__nadocTest.animPlayer.getCurrentTime())).toBeCloseTo(0.2, 4)
  const cameraPose = () => page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera.position)
  const inspectionCamera = await cameraPose()
  await page.locator('#canvas').hover({ position: { x: 300, y: 300 } })
  await page.mouse.wheel(0, -300)
  await expect.poll(cameraPose).not.toEqual(inspectionCamera)
  await page.getByRole('button', { name: 'Return to presentation', exact: true }).click()
  expect(await embedded.locator('video').evaluate(v => v.currentTime)).toBeCloseTo(0.2, 4)
  expect(await embedded.locator('video').evaluate(v => v.paused)).toBe(true)
  await page.getByRole('button', { name: 'Inspect in 3D', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Return to presentation', exact: true })).toBeVisible()
  const restored = await cameraPose()
  restored.forEach((value, i) => expect(value).toBeCloseTo(inspectionCamera[i], 4))
  await page.getByRole('button', { name: 'Return to presentation', exact: true }).click()
  await page.getByRole('button', { name: 'Close presentation', exact: true }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByText('Download offline presentation', { exact: true }).click()
  const download = await downloaded, destination = testInfo.outputPath('offline-talk.html')
  await download.saveAs(destination)
  // The fixed library survives reload and reuses the browser-owned local copy.
  await page.reload()
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async example => {
    const api = await import('/src/api/client.js'); await api.loadDesign(example)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel').classList.remove('locked-hidden')
    for (const button of document.querySelectorAll('#left-tab-strip button')) button.disabled = false
    window.__leftSidebar.refresh()
  }, path.resolve(import.meta.dirname, '..', '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  await page.locator('#tab-content-scene .compile-open').click()
  await expect(page.getByLabel('Presentation download', { exact: true })).toBeHidden()
  const localRow = page.locator('.presentation-library-list > div').filter({ hasText: 'Offline talk' })
  await localRow.getByRole('button', { name: 'Open local copy', exact: true }).click()
  await expect(page.locator('#tab-content-scene .compile-summary')).toContainText('Presentation opened')
  await page.locator('#tab-content-scene').getByRole('button', { name: 'Play compiled', exact: true }).click()
  await page.getByRole('button', { name: 'Inspect in 3D', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Return to presentation', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close presentation', exact: true }).click()
  // A second browser profile has no local database: download everything from
  // the server once, then reopen and play with the network disabled.
  const remoteContext = await browser.newContext()
  try {
    const remote = await remoteContext.newPage()
    await remote.goto(page.url())
    await remote.waitForFunction(() => !!window.__nadocTest)
    await remote.evaluate(() => {
      document.getElementById('welcome-screen')?.classList.add('hidden')
      document.getElementById('left-panel').classList.remove('locked-hidden')
      for (const button of document.querySelectorAll('#left-tab-strip button')) button.disabled = false
      window.__leftSidebar.refresh()
    })
    await remote.locator('.left-tab-btn[data-tab="scene"]').click()
    await remote.locator('#tab-content-scene .compile-open').click()
    const remoteRow = remote.locator('.presentation-library-list > div').filter({ hasText: 'Offline talk' })
    await remoteRow.getByRole('button', { name: 'Download and open', exact: true }).click()
    await expect(remote.locator('#tab-content-scene .compile-summary')).toContainText('Saved on this device')
    await remoteContext.setOffline(true)
    await remote.locator('#tab-content-scene .compile-open').click()
    await remoteRow.getByRole('button', { name: 'Open local copy', exact: true }).click()
    await remote.locator('#tab-content-scene .compile-play').click()
    const localVideo = remote.frameLocator('iframe[title="Compiled presentation"]')
    await localVideo.locator('#replay').click()
    await expect(localVideo.locator('#status')).toContainText('Held')
    expect(await localVideo.locator('video').evaluate(v => v.videoWidth)).toBe(1280)
  } finally { await remoteContext.close() }
  const offline = await browser.newContext({ offline: true })
  try {
    const viewer = await offline.newPage(), external = [], failures = []
    viewer.on('request', req => { if (/^https?:/.test(req.url())) external.push(req.url()) })
    viewer.on('pageerror', error => failures.push(error.message))
    await viewer.goto(pathToFileURL(destination).href)
    await expect(viewer.locator('#status')).toContainText('1 / 2')
    await viewer.locator('#replay').click()
    await expect(viewer.locator('#status')).toContainText('Held')
    expect(await viewer.locator('video').evaluate(v => v.videoWidth)).toBe(1280)
    await viewer.locator('#next').click()
    await expect(viewer.locator('#status')).toContainText('2 / 2')
    await expect(viewer.locator('#status')).toContainText('Held')
    await viewer.locator('#back').click()
    await expect(viewer.locator('#status')).toContainText('1 / 2 · Held')
    await expect(viewer.locator('#poster')).toBeVisible()
    await viewer.locator('#replay').click()
    await expect(viewer.locator('#status')).toContainText('Held')
    expect(external).toEqual([]); expect(failures).toEqual([])
  } finally { await offline.close() }
  expect(errors).toEqual([])
})
