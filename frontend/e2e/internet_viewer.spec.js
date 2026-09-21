import { test, expect } from '@playwright/test'
import http from 'node:http'
import https from 'node:https'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import * as THREE from 'three'
import { prepareScene } from '../src/viewer/prepared_scene.js'
import { createPreparedHost } from '../../scripts/prepared_view_host.mjs'

// Test-only TLS terminator models the provider. Certificates live in mkdtemp and
// afterAll removes them even after assertion failure. No workspace/editor writes.
let root, host, proxy, share, upstreamPort
test.beforeAll(async () => {
  root = await mkdtemp(join(tmpdir(), 'nadoc-internet-e2e-'))
  const key = join(root, 'key.pem'), cert = join(root, 'cert.pem')
  await promisify(execFile)('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=127.0.0.1'])
  proxy = https.createServer({ key: await readFile(key), cert: await readFile(cert) }, (req, res) => {
    const upstream = http.request({ hostname: '127.0.0.1', port: upstreamPort, path: req.url, method: req.method, headers: req.headers }, incoming => { res.writeHead(incoming.statusCode, incoming.headers); incoming.pipe(res) })
    upstream.on('error', () => { res.writeHead(503); res.end() }); req.pipe(upstream)
  })
  await new Promise(ok => proxy.listen(0, '127.0.0.1', ok))
  host = await createPreparedHost({ dist: resolve('dist'), publicOrigin: `https://127.0.0.1:${proxy.address().port}` })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  upstreamPort = host.server.address().port
  const scene = new THREE.Scene(); scene.add(new THREE.Mesh(new THREE.BoxGeometry(10, 8, 6), new THREE.MeshBasicMaterial({ color: '#36aaff' })))
  share = host.createShare(Buffer.from(prepareScene({ scene, title: 'Password protected design', camera: { position: [20, 15, 25], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' } })))
})
test.afterAll(async () => { host?.stop(); proxy?.close(); proxy?.closeAllConnections(); if (root) await rm(root, { recursive: true, force: true }) })
test('ordinary HTTPS browser joins by name and password, then navigates independently', async ({ page, context }) => {
  const errors = [], downloads = [], requests = []
  page.on('pageerror', e => errors.push(e.message)); page.on('download', d => downloads.push(d.suggestedFilename()))
  page.on('request', r => requests.push(r.url()))
  await page.goto(share.url)
  await expect(page.locator('#meeting-password')).toBeVisible()
  await page.locator('#guest-name').fill('Remote guest')
  await page.locator('#meeting-password').fill('incorrect')
  await page.locator('#join-submit').click()
  await expect(page.locator('#join-error')).toContainText('Incorrect meeting password')
  expect(requests.some(url => url.endsWith('/scene'))).toBe(false)
  await page.locator('#meeting-password').fill(share.password)
  await page.locator('#join-submit').click()
  await expect(page.locator('#join')).not.toBeVisible()
  await expect(page.locator('#title')).toHaveText('Password protected design')
  expect((await context.cookies()).find(c => c.name.startsWith('nadoc_view_'))).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Strict' })
  expect(requests.some(url => url.includes(share.password))).toBe(false)
  expect((await page.request.get(new URL('/host/shares', share.url).href)).status()).toBe(404)
  const canvas = page.locator('#canvas'), box = await canvas.boundingBox()
  await page.evaluate(() => new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok))))
  const before = await canvas.screenshot()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down()
  await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 8 }); await page.mouse.up()
  await page.waitForTimeout(250)
  expect((await canvas.screenshot()).equals(before)).toBe(false)
  expect(errors).toEqual([]); expect(downloads).toEqual([])
  host.stop()
  await expect(page.locator('#guest')).toContainText('Host disconnected', { timeout: 15000 })
})
