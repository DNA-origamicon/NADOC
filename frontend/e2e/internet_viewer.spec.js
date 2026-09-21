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
// afterEach removes them even after assertion failure. No workspace/editor writes.
let root, host, proxy, share, upstreamPort
test.beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), 'nadoc-internet-e2e-'))
  const key = join(root, 'key.pem'), cert = join(root, 'cert.pem')
  await promisify(execFile)('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=127.0.0.1'])
  proxy = https.createServer({ key: await readFile(key), cert: await readFile(cert) }, (req, res) => {
    const upstream = http.request({ hostname: '127.0.0.1', port: upstreamPort, path: req.url, method: req.method, headers: req.headers }, incoming => { res.writeHead(incoming.statusCode, incoming.headers); incoming.pipe(res) })
    upstream.on('error', () => { if (!res.headersSent) res.writeHead(503); res.end() }); res.on('close', () => upstream.destroy()); req.pipe(upstream)
  })
  await new Promise(ok => proxy.listen(0, '127.0.0.1', ok))
  host = await createPreparedHost({ dist: resolve('dist'), publicOrigin: `https://127.0.0.1:${proxy.address().port}` })
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  upstreamPort = host.server.address().port
  const scene = new THREE.Scene(); scene.add(new THREE.Mesh(new THREE.BoxGeometry(10, 8, 6), new THREE.MeshBasicMaterial({ color: '#36aaff' })))
  share = host.createShare(Buffer.from(prepareScene({ scene, title: 'Password protected design', camera: { position: [20, 15, 25], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' } })))
})
test.afterEach(async () => { host?.stop(); proxy?.close(); proxy?.closeAllConnections(); if (root) await rm(root, { recursive: true, force: true }) })
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
  await expect(page.locator('[data-connection]')).toContainText('not sharing')
  expect((await context.cookies()).find(c => c.name.startsWith('nadoc_view_'))).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Strict' })
  expect(requests.some(url => url.includes(share.password))).toBe(false)
  expect((await page.request.get(new URL('/host/shares', share.url).href)).status()).toBe(404)
  const canvas = page.locator('#canvas'), box = await canvas.boundingBox()
  await page.evaluate(() => new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok))))
  const before = await canvas.screenshot()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down()
  await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 8 }); await page.mouse.up()
  await page.waitForTimeout(250)
  expect(errors).toEqual([])
  expect((await canvas.screenshot()).equals(before)).toBe(false)
  expect(errors).toEqual([]); expect(downloads).toEqual([])
  host.stop()
  await expect(page.locator('#guest')).toContainText('Host disconnected', { timeout: 15000 })
})

test('presenter camera changes leave guests free until Jump or Follow; input and disconnect restore independence', async ({ browser }) => {
  const contexts = [], errors = []
  const open = async (url, name) => {
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 720 } }); contexts.push(context)
    const page = await context.newPage(); page.on('pageerror', e => errors.push(e.message))
    await page.goto(url); await page.locator('#guest-name').fill(name); await page.locator('#meeting-password').fill(share.password); await page.locator('#join-submit').click()
    await expect(page.locator('#join')).not.toBeVisible()
    await page.evaluate(() => new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok))))
    return page
  }
  const drag = async page => { const box = await page.locator('#canvas').boundingBox(); await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down(); await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 10 }); await page.mouse.up(); await page.waitForTimeout(350) }
  const state = page => page.evaluate(async id => (await (await fetch(`/meeting/${id}/status`)).json()).presentation, share.id)
  try {
    const presenter = await open(share.presenterUrl, 'Presenter'), guest = await open(share.url, 'Guest')
    const initial = await guest.locator('#canvas').screenshot()
    await presenter.locator('[data-broadcast]').click()
    await expect(guest.locator('[data-jump]')).toBeEnabled()
    const first = (await state(guest)).sequence
    await drag(presenter); await expect.poll(async () => (await state(guest)).sequence).toBeGreaterThan(first)
    expect((await guest.locator('#canvas').screenshot()).equals(initial)).toBe(true)
    await guest.locator('[data-jump]').click(); await guest.waitForTimeout(200)
    const jumped = await guest.locator('#canvas').screenshot(); expect(jumped.equals(initial)).toBe(false)
    await drag(presenter)
    expect((await guest.locator('#canvas').screenshot()).equals(jumped)).toBe(true)
    await guest.locator('[data-follow]').click(); await drag(presenter); await guest.waitForTimeout(500)
    expect((await guest.locator('#canvas').screenshot()).equals(jumped)).toBe(false)
    await guest.screenshot({ path: test.info().outputPath('guest-follow.png') })
    await drag(guest); await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'false')
    const late = await open(share.url, 'Late guest'); await expect(late.locator('[data-jump]')).toBeEnabled()
    expect((await late.locator('#canvas').screenshot()).equals(initial)).toBe(true)
    await open(share.url, 'Fourth participant')
    const forbidden = await guest.evaluate(async ({ id, revision }) => (await fetch(`/meeting/${id}/camera`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, camera: {} }) })).status, share)
    expect(forbidden).toBe(403)
    await guest.locator('[data-follow]').click()
    await guest.context().setOffline(true)
    await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'false')
    await drag(guest)
    await guest.context().setOffline(false)
    await expect(guest.locator('[data-follow]')).toBeEnabled({ timeout: 15000 })
    await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'false')
    await guest.locator('[data-follow]').click(); await contexts[0].close()
    await expect(guest.locator('[data-follow]')).toHaveAttribute('aria-pressed', 'false')
    await expect(guest.locator('[data-connection]')).toContainText('not sharing')
    expect(errors).toEqual([])
  } finally { await Promise.all(contexts.map(context => context.close())) }
})
