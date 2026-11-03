import { test, expect } from '@playwright/test'

test.use({ viewport: { width: 1440, height: 1000 }, launchOptions: { args: ['--enable-webgl', '--ignore-gpu-blocklist'] } })

test('Help T-junction previews expose directed joining, poses and isolated viewer lifecycle', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = [], mutations = []
  page.on('pageerror', error => errors.push(error.message))
  // This preview never needs simulation catalogs or their background reconcilers.
  await page.route(/\/api\/(oxdna|md|mrdna|lammps|cando|snupi|blade)\/jobs(?:\?.*)?$/, route =>
    route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.continue())
  await page.goto('/?doc=e2e-t-junction-preview')
  await expect(page.locator('#welcome-screen')).toBeVisible()
  page.on('request', request => {
    if (/\/api\/(design|assembly)(?:\/|\?|$)/.test(request.url()) && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) mutations.push(`${request.method()} ${request.url()}`)
  })
  const open = async () => {
    await page.locator('.menu-item').filter({ has: page.getByRole('button', { name: 'Help', exact: true }) }).hover()
    await page.locator('#menu-help-experimental').hover(); await page.locator('#menu-help-t-junctions').click()
  }
  await open()
  const dialog = page.getByRole('dialog', { name: 'Routing concept preview · Bundle T-junctions' })
  const canvas = dialog.locator('canvas')
  await expect(dialog).toBeVisible()
  await expect(canvas).toBeVisible()
  await expect(dialog.locator('[data-tjunction-metrics]')).toContainText('1 scaffold cycle')
  await expect(dialog.locator('[data-tjunction-metrics]')).toContainText('2 scaffold bridges')
  await expect(dialog.locator('[role="alert"]')).toHaveCount(0)

  // An actual WebGL framebuffer must contain the colored structure, not only
  // a mounted blank canvas. Compare a center-region read with its background.
  const pixels = await canvas.evaluate(element => new Promise(resolve => requestAnimationFrame(() => {
    const gl = element.getContext('webgl2') || element.getContext('webgl')
    if (!gl) { resolve(null); return }
    const bytes = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4)
    gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, bytes)
    let colored = 0
    for (let i = 0; i < bytes.length; i += 4) if (Math.max(bytes[i], bytes[i + 1], bytes[i + 2]) - Math.min(bytes[i], bytes[i + 1], bytes[i + 2]) > 45 && Math.max(bytes[i], bytes[i + 1], bytes[i + 2]) > 80) colored++
    resolve({ colored, total: bytes.length / 4 })
  })))
  expect(pixels).not.toBeNull()
  expect(pixels.colored).toBeGreaterThan(500)
  expect(pixels.colored).toBeLessThan(pixels.total * .75)

  for (const [preset, angle, azimuth] of [['acute', '60', '0'], ['obtuse', '120', '0'], ['spatial', '90', '45'], ['offset', '90', '0']]) {
    await dialog.locator(`[data-preset="${preset}"]`).click()
    await expect(dialog.locator('[data-param="angleDeg"]')).toHaveValue(angle)
    await expect(dialog.locator('[data-param="azimuthDeg"]')).toHaveValue(azimuth)
    await expect(dialog.locator(`[data-preset="${preset}"]`)).toHaveAttribute('aria-pressed', 'true')
    await expect(dialog.locator('[data-tjunction-metrics]')).toContainText('1 scaffold cycle')
  }
  await dialog.locator('[data-param="attachment"]').fill('0.72')
  await expect(dialog.locator('[data-readout="attachment"]')).toContainText('72%')
  await dialog.locator('[data-control="stage"]').selectOption('separate')
  await expect(dialog.locator('[data-tjunction-metrics]')).toContainText('2 scaffold cycles')
  await expect(dialog.locator('[data-tjunction-metrics]')).toContainText('0 scaffold bridges')
  await dialog.locator('[data-control="stage"]').selectOption('joined')
  await dialog.locator('[data-control="representation"]').selectOption('scaffold')
  await dialog.locator('[data-control="highlight"]').uncheck()
  await dialog.locator('[data-control="highlight"]').check()
  const beforeOrbit = await canvas.screenshot()
  const bounds = await canvas.boundingBox()
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  await page.mouse.down()
  await page.mouse.move(bounds.x + bounds.width / 2 + 100, bounds.y + bounds.height / 2 + 40, { steps: 8 })
  await page.mouse.up()
  await page.waitForTimeout(250)
  const afterOrbit = await canvas.screenshot()
  expect(beforeOrbit.equals(afterOrbit)).toBe(false)
  await dialog.locator('[data-action="reset"]').click()
  await page.setViewportSize({ width: 800, height: 700 })
  await expect.poll(() => dialog.locator('.modal__body').evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('#welcome-screen')).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await open()
  await expect(canvas).toBeVisible()
  await expect(dialog.locator('[data-tjunction-metrics]')).toContainText('1 scaffold cycle')
  await dialog.getByRole('button', { name: 'Close', exact: true }).last().click()
  await expect(dialog).toHaveCount(0)
  expect(mutations).toEqual([])
  expect(errors).toEqual([])
})
