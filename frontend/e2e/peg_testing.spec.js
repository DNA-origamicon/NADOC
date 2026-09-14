import { test, expect } from '@playwright/test'

test.use({ launchOptions: { args: ['--enable-webgl', '--ignore-gpu-blocklist', '--use-angle=gl'] } })

test('Help PEG toggle, controls, sampling export, and close/reopen lifecycle', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  // This playground has no job API dependency. Keep background startup polls
  // from reconciling unrelated existing simulation jobs in the shared workspace.
  await page.route(/\/(oxdna|md|mrdna|lammps)\/jobs(?:\?.*)?$/, route =>
    route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.continue())
  await page.goto('/')
  await page.locator('.menu-item').filter({ has: page.getByRole('button', { name: 'Help', exact: true }) }).hover()
  await page.locator('#menu-help-peg-testing').click()
  const dialog = page.locator('.peg-testing')
  await expect(dialog).toBeVisible()
  await expect(page.locator('#menu-help-peg-testing')).toHaveAttribute('aria-pressed', 'true')
  await expect(dialog.locator('[data-peg=backend]')).toContainText('GPU Monte Carlo')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => dialog.locator('.modal__body').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
  await page.setViewportSize({ width: 1280, height: 900 })
  await expect(dialog.locator('[data-peg=progress]')).toContainText('Burn-in')
  const contour = await dialog.locator('[data-peg=contour]').textContent()
  const neutralReference = await dialog.locator('[data-peg=reference]').textContent()
  await dialog.locator('[data-peg=field]').fill('-0.03')
  await dialog.locator('[data-peg=field]').dispatchEvent('change')
  await expect(dialog.locator('[data-peg=reference]')).toHaveText(neutralReference)
  await dialog.locator('[data-peg=preset]').selectOption('charged')
  const compressed = parseFloat(await dialog.locator('[data-peg=reference]').textContent())
  await dialog.locator('[data-peg=field]').fill('0.03')
  await dialog.locator('[data-peg=field]').dispatchEvent('change')
  expect(parseFloat(await dialog.locator('[data-peg=reference]').textContent())).toBeGreaterThan(compressed)
  await expect(dialog.locator('[data-peg=contour]')).toHaveText(contour)
  await dialog.locator('[data-peg=preset]').selectOption('screened')
  await expect(dialog.locator('[data-peg=screening]')).toBeEnabled()
  await dialog.locator('[data-peg=preset]').selectOption('free')
  await expect(dialog.locator('[data-peg=profile]')).toBeDisabled()
  await expect(dialog.locator('[data-peg=physics]')).toContainText('exact FJC')
  await dialog.locator('[data-peg=compute]').selectOption('cpu')
  await expect(dialog.locator('[data-peg=backend]')).toContainText('CPU Monte Carlo')
  await dialog.locator('[data-peg=pause]').click()
  await expect(dialog.locator('[data-peg=pause]')).toHaveText('Resume')
  const progress = await dialog.locator('[data-peg=progress]').textContent()
  await page.waitForTimeout(650)
  await expect(dialog.locator('[data-peg=progress]')).toHaveText(progress)
  const downloaded = page.waitForEvent('download')
  await dialog.locator('[data-peg=export]').click()
  const download = await downloaded
  const stream = await download.createReadStream()
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  const payload = JSON.parse(Buffer.concat(chunks).toString())
  expect(payload.parameters.wall).toBe(false)
  expect(payload.coordinatesNmRGBA).toHaveLength(64 * 25 * 4)
  expect(payload.samplesAreCorrelated).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('#menu-help-peg-testing')).toHaveAttribute('aria-pressed', 'false')
  await page.locator('.menu-item').filter({ has: page.getByRole('button', { name: 'Help', exact: true }) }).hover()
  await page.locator('#menu-help-peg-testing').click()
  await expect(dialog.locator('[data-peg=backend]')).toContainText('GPU Monte Carlo')
  // Exercise the actual toggle's second-click path while the overlay is open.
  await page.locator('#menu-help-peg-testing').evaluate(button => button.click())
  await expect(dialog).toHaveCount(0)
  expect(errors).toEqual([])
})

test('GPU sampler agrees with independent statistical mechanics and preserves geometry', async ({ page }) => {
  await page.route('**/__peg_harness', route => route.fulfill({ contentType: 'text/html', body: '<html><body></body></html>' }))
  await page.goto('/__peg_harness')
  const errors = []
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  const results = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { createPegSampler } = await import('/src/scene/peg_gpu.js')
    const m = await import('/src/scene/peg_model.js')
    const renderer = new THREE.WebGLRenderer()
    const results = []
    try {
      for (const overrides of [
        { wall: false, field: 0, charge: 0 },
        { wall: false, field: 0.03, charge: 1 },
        { wall: true, field: -0.03, charge: 1 },
        { wall: true, field: 0.03, charge: 1, screening: 2 },
      ]) {
        const p = { ...m.PEG_DEFAULTS, segments: 8, chains: 128, ...overrides }
        const sampler = createPegSampler(renderer, p)
        let mean = 0, r2 = 0, samples = 0
        for (let batch = 0; batch < 30; batch++) {
          sampler.step(100)
          const metrics = m.pegMetrics(sampler.read(), p)
          if (batch >= 10) { mean += metrics.meanHeight; r2 += metrics.meanR2; samples++ }
        }
        const data = sampler.read(), metrics = m.pegMetrics(data, p)
        let anchorsFixed = true
        for (let c = 0; c < p.chains; c++) for (let d = 0; d < 3; d++) if (data[c * 9 * 4 + d] !== 0) anchorsFixed = false
        results.push({ backend: sampler.backend, mean: mean / samples, r2: r2 / samples,
          reference: m.heightReference(p, 48).mean, wall: p.wall, maxBondError: metrics.maxBondError, minZ: metrics.minZ, anchorsFixed })
        sampler.dispose()
      }
      const longP = { ...m.PEG_DEFAULTS, segments: 64 }
      const long = createPegSampler(renderer, longP)
      long.step(200)
      const longMetrics = m.pegMetrics(long.read(), longP)
      results.push({ backend: long.backend, geometryOnly: true, maxBondError: longMetrics.maxBondError,
        wall: true, minZ: longMetrics.minZ, anchorsFixed: true })
      long.dispose()
      const originalHas = renderer.extensions.has.bind(renderer.extensions)
      renderer.extensions.has = name => name === 'EXT_color_buffer_float' ? false : originalHas(name)
      const fallback = createPegSampler(renderer, { ...m.PEG_DEFAULTS, segments: 8 })
      fallback.step(20)
      if (!fallback.backend.startsWith('CPU') || !fallback.read().every(Number.isFinite)) throw new Error('Automatic CPU fallback failed')
      fallback.dispose()
    } finally { renderer.dispose(); renderer.forceContextLoss() }
    return results
  })
  for (const result of results) {
    expect(result.backend).toContain('GPU Monte Carlo')
    if (!result.geometryOnly) expect(Math.abs(result.mean - result.reference)).toBeLessThan(0.12)
    expect(result.maxBondError).toBeLessThan(0.002)
    expect(result.anchorsFixed).toBe(true)
    if (result.wall) expect(result.minZ).toBeGreaterThanOrEqual(0)
  }
  expect(Math.abs(results[0].r2 - 8 * 0.7 ** 2)).toBeLessThan(0.2)
  expect(errors).toEqual([])
})
