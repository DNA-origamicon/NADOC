import { test, expect } from '@playwright/test'
import { access, writeFile, unlink } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
import { decodeContainer } from '../src/viewer/package_container.js'

// Read-only duplex load. No design authoring or saving. Host rooms/links stay in
// memory; afterAll removes its test-port credential. The normal reporter cleans
// screenshots; afterEach closes guests. Build frontend/dist first so the host
// and the editor bridge agree on the viewer build identity.
const root = path.resolve(import.meta.dirname, '../..')
const control = shareControlFile(path.join(root, 'frontend'), Number(process.env.NADOC_E2E_FRONTEND_PORT || 5175))
let host, ownsControl = false
const guests = []
test.beforeAll(async () => {
  try { await access(control); throw new Error('Existing test sharing credential must not be overwritten') } catch (error) { if (error.code !== 'ENOENT') throw error }
  host = await createPreparedHost({ dist: path.join(root, 'frontend/dist') })
  await new Promise(resolve => host.server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${host.server.address().port}`
  host.setPublicBase(url)
  await writeFile(control, JSON.stringify({ url, token: host.controlToken }), { flag: 'wx', mode: 0o600 })
  ownsControl = true
})
test.afterEach(async () => { for (const guest of guests.splice(0)) await guest.close() })
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(control).catch(() => {}) })

test('presentation guests receive duplex overlay layers and live display changes', async ({ page, browser }, testInfo) => {
  test.setTimeout(120_000)
  test.skip(!existsSync(path.join(root, 'workspace/duplex.nadoc')), 'duplex.nadoc is not installed')
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/?doc=e2e-duplex-overlay-share')
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.loadDesign('workspace/duplex.nadoc')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.configureMultiOverlay({ count: 2,
      representations: ['full', 'cylinders'], opacities: [1, .4], separation: .2 })
  })
  await page.locator('#menu-file-sharing').evaluate(el => el.click())
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-stop-host]')).toBeEnabled({ timeout: 30_000 })
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({ timeout: 30_000 })
  const url = await page.locator('#share-link-dialog [data-link]').inputValue()
  await page.locator('#share-link-dialog [data-close]').click()
  const guest = await browser.newPage({ viewport: { width: 1000, height: 800 } })
  guests.push(guest)
  guest.on('pageerror', error => errors.push(error.message))
  const received = []
  guest.on('response', async response => {
    if (!response.ok() || !new URL(response.url()).pathname.endsWith('/scene')) return
    const bytes = await response.body()
    received.push(decodeContainer(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)))
  })
  await guest.goto(url)
  await expect(guest.locator('#guest-name')).toBeVisible({ timeout: 10_000 }).catch(async error => {
    console.log('Guest entry:', await guest.locator('body').innerText())
    throw error
  })
  await guest.locator('#guest-name').fill('Overlay reviewer')
  await guest.locator('#join-submit').click()
  await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 30_000 })
  await expect.poll(() => received.at(-1)?.view.overlay?.length).toBe(2)
  const initial = received.at(-1)
  expect(initial.root.children[0].matrix[12]).toBeLessThan(0)
  expect(initial.root.children[1].matrix[12]).toBeGreaterThan(0)
  expect(initial.materials.some(material => Math.abs(material.opacity - .4) < 1e-6)).toBe(true)
  const box = await guest.locator('#canvas').boundingBox()
  await guest.mouse.move(box.x + box.width * .45, box.y + box.height * .5)
  await guest.mouse.down()
  await guest.mouse.move(box.x + box.width * .6, box.y + box.height * .55, { steps: 8 })
  await guest.mouse.up()
  if (process.env.NADOC_COMPARISON_REVIEW) {
    await guest.screenshot({ path: testInfo.outputPath('guest-overlay.png') })
    await guest.waitForTimeout(20_000)
  }
  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({ count: 3,
    representations: ['full', 'cylinders', 'mrdna-fine'], opacities: [1, .25, .6], separation: .3 }))
  await expect.poll(() => received.at(-1)?.view.overlay?.length, { timeout: 30_000 }).toBe(3)
  expect(received.at(-1).materials.some(material => Math.abs(material.opacity - .25) < 1e-6)).toBe(true)
  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({ count: 0 }))
  await expect.poll(() => received.at(-1)?.view.overlay, { timeout: 30_000 }).toBeUndefined()
  expect(errors).toEqual([])
})
