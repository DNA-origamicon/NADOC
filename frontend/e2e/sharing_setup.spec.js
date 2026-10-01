import jsQR from 'jsqr'
import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
async function qrPixels(svg) {
    const source = svg.cloneNode(true), size = source.viewBox.baseVal.width * 6
    source.setAttribute('width', size); source.setAttribute('height', size)
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(source)], { type: 'image/svg+xml' }))
    try {
      const image = new Image(); image.src = url; await image.decode()
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = size
      const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0, size, size)
      return { data: Array.from(ctx.getImageData(0, 0, size, size).data), size }
    } finally { URL.revokeObjectURL(url) }
  }

// Only the __e2e__ copy/history may persist; global teardown removes them and the
// isolated Vite bridge. Provider calls are intercepted: no real public room.
// Runner screenshots/traces are removed by the cleanup reporter on failure too.
test('Start waits for public access while its persistent invitation remains copyable', async ({ page }) => {
  test.setTimeout(120000)
  let started = false, polls = 0, publications = 0, shared = null
  const pending = { state: 'dns_pending', message: 'Waiting for public DNS', checks: [] }
  const ready = { state: 'ready', message: 'Public DNS and HTTPS verified', checks: [] }
  await page.route('**/__nadoc_share/**', route => {
    const action = new URL(route.request().url()).pathname.split('/').pop()
    if (action === 'links') return route.fulfill({ json: { id: 'a'.repeat(32), key: JSON.parse(route.request().postData()).key, url: 'https://example.invalid/viewer#invite=guest&password=required', qrUrl: 'https://example.invalid/viewer#invite=qr-guest&entry=qr', password: 'test-password' } })
    if (action === 'preparing') return route.fulfill({ json: {} })
    if (action === 'start') { started = true; return route.fulfill({ json: { shares: [], publicAccess: pending } }) }
    if (action === 'stop') { started = false; shared = null; return route.fulfill({ json: {} }) }
    if (action === 'create') {
      expect(polls).toBeGreaterThan(1); publications++
      shared = { key: 'part:__e2e__auto-sharing', id: 'a'.repeat(32), title: 'Setup test', url: 'https://example.invalid/viewer#invite=guest&password=required', qrUrl: 'https://example.invalid/viewer#invite=qr-guest&entry=qr', password: 'test-password', expiresAt: Date.now() + 7200000 }
      return route.fulfill({ json: shared })
    }
    return route.fulfill({ json: { running: started, shares: shared ? [shared] : [], ...(started ? { publicAccess: ++polls > 1 ? ready : pending } : {}) } })
  })
  const design = JSON.parse(readFileSync(new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)))
  design.id = '__e2e__auto-sharing'; design.metadata.name = '__e2e__auto-sharing'
  await page.goto('/?doc=__e2e__auto-sharing')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js'); await api.importDesign(JSON.stringify(design)); await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden'); document.getElementById('menu-file-sharing').click()
  }, design)
  const dialog = page.locator('#share-link-dialog')
  await expect(dialog.locator('[data-host-setup]')).toHaveCount(0)
  await expect(dialog.locator('[data-create]')).toBeEnabled()
  await expect(dialog.locator('[data-stop-host]')).toBeDisabled()
  await expect(dialog.locator('[data-copy-link]')).toBeVisible()
  await dialog.locator('[data-create]').click()
  await expect(dialog.locator('[data-status]')).toHaveText('Waiting for public DNS')
  expect(publications).toBe(0)
  await expect(dialog.locator('[data-stop-host]')).toBeEnabled({ timeout: 20000 })
  await expect(dialog.locator('[data-create]')).toBeDisabled()
  await expect(dialog.locator('[data-stop-host]')).toBeEnabled()
  await expect(dialog.locator('[data-status]')).toBeEmpty()
  expect(publications).toBe(1)
  await page.evaluate(() => { window.__copiedShare = ''; navigator.clipboard.writeText = async value => { window.__copiedShare = value } })
  await dialog.locator('[data-copy-link]').click()
  expect(await page.evaluate(() => window.__copiedShare)).toBe('https://example.invalid/viewer#invite=guest&password=required')
  await expect(dialog.locator('[data-link]')).toHaveValue('https://example.invalid/viewer#invite=guest&password=required')
  await expect(dialog.locator('[data-password]')).toHaveValue('test-password')
  const qr = dialog.locator('[data-guest-qr] svg')
  await expect(qr).toBeVisible()
  const raster = await qr.evaluate(qrPixels)
  expect(jsQR(new Uint8ClampedArray(raster.data), raster.size, raster.size)?.data).toBe(shared.qrUrl)
  await page.context().addInitScript(() => { window.print = () => { window.__printRequested = true } })
  const printPagePromise = page.waitForEvent('popup')
  await dialog.getByRole('button', { name: 'Print meeting target' }).click()
  const printPage = await printPagePromise
  await expect(printPage.locator('[data-room-marker]')).toBeVisible()
  await expect.poll(() => printPage.evaluate(() => window.__printRequested)).toBe(true)
  const dimensions = await printPage.locator('[data-room-marker]').evaluate(el => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height }))
  expect(dimensions.width).toBeCloseTo(187.5 * 96 / 25.4, 0)
  expect(dimensions.height).toBeCloseTo(dimensions.width, 1)
  expect(await printPage.evaluate(() => window.opener)).toBeNull()
  await printPage.close()
  const largePopup = page.waitForEvent('popup')
  await dialog.getByRole('button', { name: 'Print large tracking QR' }).click()
  const largePage = await largePopup, marker = largePage.locator('[data-mobile-marker]')
  await expect(marker).toBeVisible()
  expect((await marker.boundingBox()).width).toBeCloseTo(150 * 96 / 25.4, 0)
  const largePixels = await marker.evaluate(qrPixels)
  const largeURL = new URL(jsQR(new Uint8ClampedArray(largePixels.data), largePixels.size, largePixels.size).data)
  const largeParams = new URLSearchParams(largeURL.hash.slice(1))
  expect(largeParams.get('qrmm')).toBe('150')
  expect(largeParams.get('invite')).toBe('qr-guest')
  expect(largeParams.get('entry')).toBe('qr')
  await largePage.close()


  for (const key of ['link', 'password']) {
    const field = dialog.locator(`[data-${key}]`)
    const copy = dialog.getByRole('button', { name: `Copy ${key}`, exact: true })
    await expect(field).toBeVisible()
    await expect(field).toHaveAttribute('readonly', '')
    await expect(copy.locator('svg')).toBeVisible()
    const inputBox = await field.boundingBox(), copyBox = await copy.boundingBox()
    expect(copyBox.x).toBeGreaterThanOrEqual(inputBox.x + inputBox.width)
    await field.dblclick()
    expect(await field.evaluate(input => input.value.slice(input.selectionStart, input.selectionEnd))).toBe(await field.inputValue())
  }
  await dialog.locator('[data-copy-password]').click()
  expect(await page.evaluate(() => window.__copiedShare)).toBe('test-password')
  await expect(dialog.locator('[data-status]')).toHaveText('Password copied')
  await dialog.locator('[data-close]').click()
  const presentation = page.locator('#menu-item-presentation')
  await presentation.hover()
  await expect(presentation.locator('> button')).toHaveText('Presentation')
  await expect(presentation.locator('#menu-file-export-qr-cube')).toBeVisible()
  await expect(page.locator('#menu-item-export #menu-file-export-qr-cube')).toHaveCount(0)
  await presentation.locator('#menu-presentation-qr').click()
  const qrDialog = page.locator('#presentation-qr-dialog')
  await expect(qrDialog).toBeVisible()
  const invitationPixels = await qrDialog.locator('svg').evaluate(qrPixels)
  expect(jsQR(new Uint8ClampedArray(invitationPixels.data), invitationPixels.size, invitationPixels.size)?.data).toBe(shared.qrUrl)
  await qrDialog.locator('[data-close]').click()
  await presentation.hover()
  const download = page.waitForEvent('download')
  await presentation.locator('#menu-file-export-qr-cube').click()
  expect((await download).suggestedFilename()).toBe('nadoc-qr-cube-150mm-stl.zip')
  await presentation.hover()
  await presentation.locator('#menu-presentation-stop').click()
  await expect(presentation.locator('#menu-presentation-stop')).toBeDisabled()
  await expect(presentation.locator('#menu-presentation-qr')).toBeEnabled()
  await presentation.hover()
  await presentation.locator('#menu-file-sharing').click()
  await expect(dialog.locator('[data-create]')).toBeEnabled()
  await expect(dialog.locator('[data-stop-host]')).toBeDisabled()
  await expect(dialog.locator('[data-copy-link]')).toBeVisible()
  await expect(dialog.locator('[data-copy-password]')).toBeVisible()
  await expect(dialog.locator('[data-guest-qr] svg')).toBeVisible()
  await page.route('**/__nadoc_share/start', route => route.fulfill({ status: 503, json: { error: 'Host connection failed' } }))
  await dialog.locator('[data-create]').click()
  const errors = dialog.locator('[data-error]')
  await expect(errors).toBeVisible()
  await expect(errors).not.toHaveAttribute('open')
  await expect(errors.locator('pre')).not.toBeVisible()
  await errors.locator('summary').click()
  await expect(errors.locator('pre')).toHaveText('Host connection failed')
  await expect(errors.locator('pre')).toBeVisible()
})
