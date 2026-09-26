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
let browser, share
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
  await browser?.close()
  if (share) await api(`/host/shares/${share.id}`, { method: 'DELETE' })
}
