import { test, expect } from '@playwright/test'
import { access, writeFile, unlink } from 'node:fs/promises'
import path from 'node:path'
import { gunzipSync } from 'node:zlib'
import { createHash } from 'node:crypto'
import { decodeContainer } from '../src/viewer/package_container.js'
import { sceneChannels } from '../src/viewer/trajectory_clip.js'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'
import { shareControlFile } from '../../scripts/prepared_share_control.mjs'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persisted inventory: __e2e__animation-share .nadoc/project history (global teardown),
// test-port host credential (afterAll). Host scenes/links are memory-only. No screenshots saved.
const root = path.resolve(import.meta.dirname, '../..')
const control = shareControlFile(path.join(root, 'frontend'), Number(process.env.NADOC_E2E_FRONTEND_PORT || 5175))
let host, ownsControl = false
const guests = []
test.afterEach(async () => { for (const guest of guests.splice(0)) await guest.close() })
test.beforeAll(async () => {
  try { await access(control); throw new Error('An existing test sharing credential must not be overwritten') } catch (e) { if (e.code !== 'ENOENT') throw e }
  host = await createPreparedHost({ dist: path.join(root, 'frontend/dist') })
  await new Promise(resolve => host.server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  await writeFile(control, JSON.stringify({ url, token: host.controlToken }), { flag: 'wx', mode: 0o600 }); ownsControl = true
})
test.afterAll(async () => { host?.stop(); if (ownsControl) await unlink(control).catch(() => {}) })

test('link viewers receive a full authored sequence, captions and automatic/manual perspective locks', async ({ page, browser }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page)
  page.on('response', async response => {
    if (response.status() >= 400 && response.url().includes('/__nadoc_share/')) console.log('Sharing request failed', new URL(response.url()).pathname, (await response.json().catch(() => ({}))).error)
  })
  await loadScaffoldedPart(page, { doc: '__e2e__animation-share', name: 'animation-share' })
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  const id = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.addBundleSegment({ cells: [[2, 2]], lengthBp: 16 })
    await api.createAnimation('Shared sequence', 30, false)
    const design = window.__nadocTest.store.getState().currentDesign, animation = design.animations.at(-1)
    await api.createKeyframe(animation.id, { feature_log_index: 0, hold_duration_s: 2, transition_duration_s: 1, text: 'First stage', spin_axis: 'z', spin_rotations: .25 })
    await api.createKeyframe(animation.id, { feature_log_index: design.feature_log_cursor, hold_duration_s: 2, transition_duration_s: 1, text: 'Second stage', spin_axis: 'z', spin_rotations: .25 })
    return animation.id
  })
  await page.locator('#animation-select').selectOption(id)
  if (await page.locator('#anim-bounce-btn').evaluate(el => el.classList.contains('is-active'))) await page.locator('#anim-bounce-btn').click()
  await page.locator('#menu-file-sharing').evaluate(el => el.click())
  await expect(page.locator('#share-link-dialog [data-create]')).toBeEnabled()
  await page.locator('#share-link-dialog [data-create]').click()
  await expect(page.locator('#share-link-dialog [data-link]')).toBeVisible({ timeout: 45000 })
  const url = await page.locator('#share-link-dialog [data-link]').inputValue()
  await page.locator('#share-link-dialog [data-close]').click()
  async function join(name) {
    const guest = await browser.newPage(); guests.push(guest)
    await guest.setViewportSize({ width: 900, height: 700 })
    await guest.goto(url); await guest.locator('#guest-name').fill(name); await guest.locator('#join-submit').click()
    await expect(guest.locator('#join')).not.toBeVisible()
    return guest
  }
  const guest = await join('Viewer one'), guestErrors = trackConsoleErrors(guest)
  await expect(guest.locator('#status')).toContainText('Static snapshot', { timeout: 30000 })
  const lock = page.locator('.presentation-view-lock'), play = page.locator('#anim-playpause-btn')
  await lock.click()
  await expect(lock).toHaveAttribute('aria-pressed', 'true').catch(async error => { console.log('Lock error:', await page.locator('.presentation-error').innerText()); throw error })
  await expect(guest.locator('[data-follow]')).toBeDisabled()
  await expect(guest.locator('#reset')).toBeDisabled()
  await lock.click()
  await expect(guest.locator('#reset')).toBeEnabled()
  const frames = [], geometry = [], sceneGeometry = []
  guest.on('response', async response => {
    if (response.url().includes('/scene?') && response.ok()) {
      const bytes = await response.body()
      const data = decodeContainer(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength))
      sceneGeometry.push(createHash('sha256').update(new Uint8Array(sceneChannels(data).values.buffer)).digest('hex'))
    }
    if (response.url().includes('/live-frame?') && response.ok()) {
      const header = response.headers()['x-nadoc-animation']
      if (header) {
        frames.push(JSON.parse(decodeURIComponent(header)))
        const raw = gunzipSync(await response.body())
        geometry.push({ changes: raw.readUInt32LE(0), hash: createHash('sha256').update(raw).digest('hex') })
      }
    }
  })
  console.log('Sharing animation: starting sequence')
  await play.click()
  await expect(lock).toHaveAttribute('aria-pressed', 'true')
  await expect(lock).toBeDisabled()
  await expect(guest.locator('#anim-text-overlay')).toHaveText('First stage', { timeout: 30000 })
  await expect(guest.locator('#anim-text-overlay')).toBeVisible()
  await play.click() // Pause keeps the animation's automatic lock.
  await expect(play).toHaveAttribute('title', 'Play')
  console.log('Sharing animation: paused first stage, joining late viewer')
  const late = await join('Viewer two'), lateErrors = trackConsoleErrors(late)
  await expect(late.locator('[data-follow]')).toBeDisabled()
  await expect(late.locator('#anim-text-overlay')).toHaveText('First stage', { timeout: 30000 })
  await page.locator('#anim-scrub').evaluate(el => {
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); el.value = '1.5'
    el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  })
  await expect.poll(() => frames.some(f => f?.time === 1.5)).toBe(true).catch(async error => { console.log('Seek diagnostic:', frames.map(f => f?.time), await page.locator('.presentation-error').innerText(), await page.locator('#anim-time-display').innerText(), await page.locator('#anim-scrub').inputValue(), errors, guestErrors); throw error })
  await guest.waitForTimeout(300)
  const paused = await guest.locator('canvas').screenshot()
  const box = await guest.locator('canvas').boundingBox()
  await guest.mouse.move(box.x + 200, box.y + 200); await guest.mouse.down()
  await guest.mouse.move(box.x + 350, box.y + 250, { steps: 10 }); await guest.mouse.up(); await guest.mouse.wheel(0, 500)
  await guest.waitForTimeout(150)
  expect(paused.equals(await guest.locator('canvas').screenshot())).toBe(true)
  console.log('Sharing animation: locked gesture verified, resuming')
  await play.click()
  await expect(guest.locator('#anim-text-overlay')).toHaveText('Second stage', { timeout: 30000 })
  expect(paused.equals(await guest.locator('canvas').screenshot())).toBe(false)
  await expect(lock).toBeEnabled({ timeout: 45000 })
  await expect(lock).toHaveAttribute('aria-pressed', 'false')
  await expect(guest.locator('#reset')).toBeEnabled()
  await expect(late.locator('#reset')).toBeEnabled()
  await expect.poll(() => frames.some(f => f?.time === f?.duration)).toBe(true)
  expect(geometry.some(f => f.changes > 0) || new Set(sceneGeometry).size > 1).toBe(true)
  expect(Math.max(new Set(geometry.map(f => f.hash)).size, new Set(sceneGeometry).size)).toBeGreaterThan(3)
  expect(frames.some(f => f?.text?.text === 'First stage')).toBe(true)
  expect(frames.some(f => f?.text?.text === 'Second stage')).toBe(true)
  expect(new Set(frames.filter(Boolean).map(f => JSON.stringify(f.camera.position))).size).toBeGreaterThan(3)
  // A manual lock survives an animation stop.
  await lock.click(); await play.click()
  await expect(lock).toBeDisabled()
  await play.click() // Pause, then Skip to start performs the panel's Stop action.
  await page.locator('#anim-skip-start-btn').click()
  await expect(lock).toBeEnabled()
  await expect(lock).toHaveAttribute('aria-pressed', 'true')
  await expect(guest.locator('#reset')).toBeDisabled()
  await lock.click(); await expect(guest.locator('#reset')).toBeEnabled()
  expect(errors).toEqual([]); expect(guestErrors).toEqual([]); expect(lateErrors).toEqual([])
})
