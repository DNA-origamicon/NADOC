#!/usr/bin/env node
/** Real public-relay browser check. Owns only its temporary room and browser. */
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import { shareControlFile } from './prepared_share_control.mjs'
import { hostTransport } from '../frontend/prepared_share_transport.js'
import { isPublicIPv4 } from './sharing_public_access.mjs'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test'), { build } = require('esbuild')
const root = fileURLToPath(new URL('../frontend', import.meta.url)), controlFile = shareControlFile(root)
const config = JSON.parse(await readFile(controlFile, 'utf8'))
const api = (path, options = {}) => hostTransport({ root, controlFile, config, path, options })
let browser, share, heartbeat
let heartbeatFlight = Promise.resolve()
try {
  const hostname = new URL(config.publicOrigin).hostname
  const answers = await Promise.all(['https://dns.google/resolve', 'https://cloudflare-dns.com/dns-query'].map(async endpoint => {
    const response = await fetch(`${endpoint}?name=${encodeURIComponent(hostname)}&type=A`, { headers: { Accept: 'application/dns-json' }, signal: AbortSignal.timeout(8000) })
    const value = await response.json(), ips = (value.Answer ?? []).filter(row => row.type === 1).map(row => row.data)
    assert.equal(value.Status, 0, 'Public DNS must resolve'); assert.ok(ips.length && ips.every(isPublicIPv4), 'Public relay addresses required'); return ips
  }))
  // Bundle the actual exporter, treating UI stylesheet imports as non-runtime assets.
  // The bundle and synthetic package remain in memory; no scratch files are created.
  const built = await build({ stdin: { contents: `
    import * as THREE from 'three';
    import { prepareScene } from './src/viewer/prepared_scene.js';
    export function sample() {
      const scene = new THREE.Scene(); scene.add(new THREE.Mesh(new THREE.BoxGeometry(3,8,5),new THREE.MeshBasicMaterial({color:'#36aaff'})));
      return prepareScene({scene,title:'__setup__public-check',camera:{position:[12,10,15],target:[0,0,0],up:[0,1,0],fov:55,orbitMode:'orbit'}});
    }`, resolveDir: root }, bundle: true, write: false, format: 'esm', platform: 'node', loader: { '.css': 'empty' } })
  const { sample } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'))
  const buffer = sample()
  // No workspace designs, screenshots, traces or downloads are created.
  // The temporary invitation is revoked in finally, including on browser failure.
  const enableStarted = performance.now()
  share = await api('/host/shares', { method: 'POST', headers: { 'X-NADOC-Title': '__setup__public-check' }, body: Buffer.from(buffer) })
  const enableMs = performance.now() - enableStarted
  assert.ok(share.password, 'Internet invitations must have a password')
  browser = await chromium.launch({ headless: true, args: [`--host-resolver-rules=MAP ${hostname} ${answers[0][0]},EXCLUDE localhost`, '--no-proxy-server'] })
  const page = await browser.newPage(), errors = []; page.on('pageerror', error => errors.push(error.message))
  await page.goto(share.url)
  assert.equal(await page.evaluate(async id => (await fetch(`/meeting/${id}/scene`)).status, share.id), 401)
  for (const path of ['/host/shares', '/api/design']) assert.equal(await page.evaluate(async path => (await fetch(path)).status, path), 404)
  await page.locator('#guest-name').fill('Setup verification')
  await page.locator('#meeting-password').fill('deliberately-wrong')
  await page.locator('#join-submit').click()
  await page.waitForFunction(() => document.querySelector('#join-error')?.textContent.includes('Incorrect'))
  assert.equal(await page.evaluate(async id => (await fetch(`/meeting/${id}/scene`)).status, share.id), 401)
  const joinStarted = performance.now()
  await page.locator('#meeting-password').fill(share.password); await page.locator('#join-submit').click()
  await page.locator('#join').waitFor({ state: 'hidden', timeout: 30000 })
  await page.waitForFunction(() => document.querySelector('#title')?.textContent === '__setup__public-check')
  await page.evaluate(() => new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok))))
  const guestReadyMs = performance.now() - joinStarted
  const canvas = page.locator('#canvas'), before = await canvas.screenshot(), box = await canvas.boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down()
  await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 10 }); await page.mouse.up()
  await page.waitForTimeout(300)
  assert.equal((await canvas.screenshot()).equals(before), false, 'Guest orbit must change the rendered view')
  // Exercise the actual host transport too: a Linux-only fixture misses WSL's
  // Windows helper allowlist, which previously rejected view-lock and drawings.
  const session = await api(`/host/shares/${share.id}/broadcast/start`, { method: 'POST' })
  const broadcast = (action, value) => api(`/host/shares/${share.id}/broadcast/${action}`, {
    method: 'POST', headers: { 'X-NADOC-Broadcast': session.lease },
    ...(value !== undefined ? { body: Buffer.from(JSON.stringify(value)) } : {}),
  })
  heartbeat = setInterval(() => { heartbeatFlight = broadcast('heartbeat').catch(error => errors.push(error.message)) }, 4000)
  await broadcast('camera', { revision: session.revision, camera: { position: [12, 10, 15], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 1000, orbitMode: 'orbit' } })
  await broadcast('view-lock', { locked: true })
  await page.waitForFunction(() => document.querySelector('#reset')?.disabled && document.querySelector('[data-follow]')?.textContent === 'Perspective locked')
  assert.equal(await page.locator('#mode').isDisabled(), true)
  // Lock uses the same 0.9-second arrival and smooth tracking as voluntary Follow.
  // Wait for visual settling before testing navigation; relay timing and render
  // rate can leave a few interpolation frames after the lock label appears.
  await page.waitForTimeout(1000)
  let lockedImage = await canvas.screenshot(), stable = 0
  const settleDeadline = performance.now() + 10000
  while (stable < 3 && performance.now() < settleDeadline) {
    await page.waitForTimeout(150)
    const next = await canvas.screenshot()
    stable = next.equals(lockedImage) ? stable + 1 : 0
    lockedImage = next
  }
  assert.equal(stable, 3, 'Locked camera settles at the stationary presenter pose')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down()
  await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 10 }); await page.mouse.up()
  await page.mouse.wheel(0, 300)
  await page.waitForTimeout(200)
  assert.equal((await canvas.screenshot()).equals(lockedImage), true, 'Locked guests cannot orbit or zoom')
  const late = await browser.newPage()
  await late.goto(share.url)
  await late.locator('#guest-name').fill('Other guest')
  await late.locator('#meeting-password').fill(share.password)
  await late.locator('#join-submit').click()
  await late.locator('#join').waitFor({ state: 'hidden', timeout: 30000 })
  await late.waitForFunction(() => document.querySelector('#reset')?.disabled && document.querySelector('[data-follow]')?.textContent === 'Perspective locked')
  await page.waitForFunction(() => document.querySelectorAll('.meeting-presence-person').length === 3)
  await broadcast('progress', { fraction: .5 })
  await page.locator('#meeting-loading').waitFor({ state: 'visible' })
  const layers = await page.evaluate(() => {
    const loading = document.querySelector('#meeting-loading'), original = loading.getAttribute('style')
    try {
      return [...document.querySelectorAll('.meeting-presence-person')].map(person => {
        const rect = person.getBoundingClientRect()
        // Force overlap for each real roster row without altering either z-index.
        Object.assign(loading.style, { top: `${rect.top}px`, left: `${rect.left}px`, transform: 'none', pointerEvents: 'auto' })
        return { label: person.textContent, above: loading.contains(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)) }
      })
    } finally { loading.setAttribute('style', original) }
  })
  assert.deepEqual(layers.map(row => row.label).sort(), ['Me', 'Other guest', 'Presenter'].sort())
  assert.ok(layers.every(row => row.above), 'Loading visualization must cover every participant row')
  await api(`/host/shares/${share.id}/drawings`)
  await broadcast('progress', null)
  await page.locator('#meeting-loading').waitFor({ state: 'hidden' })
  await broadcast('view-lock', { locked: false })
  await page.waitForFunction(() => !document.querySelector('#reset')?.disabled)
  await late.waitForFunction(() => !document.querySelector('#reset')?.disabled)
  const unlockedImage = await canvas.screenshot()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down()
  await page.mouse.move(box.x + box.width * .6, box.y + box.height * .7, { steps: 10 }); await page.mouse.up()
  await page.waitForTimeout(300)
  assert.equal((await canvas.screenshot()).equals(unlockedImage), false, 'Unlock restores guest navigation')
  clearInterval(heartbeat); heartbeat = null; await heartbeatFlight
  await broadcast('pause')
  await late.close()
  console.log('PASS: host-transport perspective lock/unlock, locked late joining, drawing reads, and loading overlay above Presenter/Me/other guests.')
  assert.deepEqual(errors, [])
  const beforeEnd = await api('/host/shares')
  await api(`/host/shares/${share.id}`, { method: 'DELETE' })
  await page.locator('#presentation-ended').waitFor({ state: 'visible' })
  assert.equal(await page.evaluate(async id => (await fetch(`/meeting/${id}/scene`)).status, share.id), 410)
  share = null
  const afterEnd = await api('/host/shares')
  assert.equal(afterEnd.publicAccess.state, 'ready')
  assert.equal(afterEnd.buildId, beforeEnd.buildId)
  const reenableStarted = performance.now()
  share = await api('/host/shares', { method: 'POST', headers: { 'X-NADOC-Title': '__setup__public-check' }, body: Buffer.from(buffer) })
  const reenableMs = performance.now() - reenableStarted
  await page.goto(share.url)
  await page.locator('#guest-name').fill('Returning guest')
  await page.locator('#meeting-password').fill(share.password)
  const rejoinStarted = performance.now()
  await page.locator('#join-submit').click()
  await page.locator('#join').waitFor({ state: 'hidden', timeout: 30000 })
  await page.waitForFunction(() => document.querySelector('#title')?.textContent === '__setup__public-check')
  const rejoinMs = performance.now() - rejoinStarted
  console.log('Sharing timings (synthetic scene, warm public connection): ' + JSON.stringify({ enableMs: Math.round(enableMs), guestReadyMs: Math.round(guestReadyMs), reenableMs: Math.round(reenableMs), rejoinMs: Math.round(rejoinMs) }))
  assert.deepEqual(errors, [])
  console.log('PASS: public DNS, public-relay browser HTTPS, wrong-password rejection, correct-password scene load, navigation, immediate revocation, warm re-enabling, and editor/management isolation. No private DNS or certificate override used.')
} finally {
  clearInterval(heartbeat); await heartbeatFlight
  await browser?.close()
  if (share) await api(`/host/shares/${share.id}`, { method: 'DELETE' })
}
