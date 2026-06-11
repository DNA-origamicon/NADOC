/**
 * build-primitives — bake a looping hover-preview GIF (+ a static poster PNG)
 * for every primitive design in workspace/Primitives/.
 *
 * It drives the REAL app in headless Chromium so previews use the exact renderer
 * the editor shows: for each <name>.nadoc it loads the design, then renders it
 * through the design's saved camera poses (scene/primitive_preview_capture.js),
 * encoding the frames to a GIF with the already-bundled gifenc. Output lands next
 * to the design as <name>.gif and <name>.poster.png, which the backend serves to
 * the Primitives panel (routes_primitives.py).
 *
 * Requires both dev servers running (backend :8000, Vite :5173):
 *     just dev          # terminal 1
 *     just frontend     # terminal 2
 *     just build-primitives
 *
 * The encoder is intentionally isolated in capturePosesGif — swapping GIF for
 * animated WebP later is a change there + the file extension here, nothing else.
 */
import { chromium } from '@playwright/test'
import { readdir, writeFile, access } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const FRONTEND_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const PRIMITIVES_DIR = path.resolve(FRONTEND_DIR, '..', 'workspace', 'Primitives')
const WORKSPACE_REL = 'workspace/Primitives'
const APP = 'http://127.0.0.1:5173'
const API = 'http://localhost:8000/api'

const CAPTURE = { maxWidth: 360, fps: 18, stepsPerSegment: 16 }

async function serversUp() {
  try { await fetch(`${API}/primitives`); await fetch(APP); return true }
  catch { return false }
}

async function buildOne(browser, file) {
  const stem = file.replace(/\.nadoc$/, '')
  const doc = `primitives-build-${stem}`
  const page = await browser.newPage({ viewport: { width: 960, height: 720 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  try {
    await page.goto(`${APP}/?doc=${doc}`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('#canvas')

    // Load this primitive into the doc's server state, then nudge the app to pull it.
    const res = await page.request.post(`${API}/design/load`, {
      data: { path: `${WORKSPACE_REL}/${file}` },
      headers: { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc },
    })
    if (!res.ok()) throw new Error(`/design/load ${res.status()} for ${file}`)
    await page.evaluate((d) => {
      const bc = new BroadcastChannel('nadoc-design')
      bc.postMessage({ type: 'design-changed', source: 'build-' + Math.random(), docId: d })
      bc.close()
      document.getElementById('welcome-screen')?.classList.add('hidden')
    }, doc)

    // Wait until the design's beads are actually in the scene (fresh doc → from 0).
    await page.waitForFunction(() => {
      let ok = false
      window.__nadocTest?.scene?.traverse((o) => {
        if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true
      })
      return ok
    }, null, { timeout: 30_000 })
    await page.waitForTimeout(400)

    const poses = await page.evaluate(() => window.__nadocTest.getDesignCameraPoseCount())
    const result = await page.evaluate(
      (opts) => window.__nadocTest.capturePrimitivePreview(opts), CAPTURE)

    if (!result) {
      console.warn(`  ⚠ ${file}: no camera poses — skipped (add poses + re-run)`)
      return false
    }
    const gif = Buffer.from(result.gifBase64, 'base64')
    const poster = Buffer.from(result.posterDataUrl.split(',')[1], 'base64')
    await writeFile(path.join(PRIMITIVES_DIR, `${stem}.gif`), gif)
    await writeFile(path.join(PRIMITIVES_DIR, `${stem}.poster.png`), poster)
    console.log(`  ✓ ${stem}: ${result.frames} frames @ ${result.width}×${result.height}, ` +
      `${poses} poses, ${(gif.length / 1024).toFixed(0)} KB gif`)
    if (errors.length) console.warn(`    (page errors: ${errors.length})`)
    return true
  } finally {
    await page.close()
  }
}

async function main() {
  if (!(await serversUp())) {
    console.error('✗ Servers not reachable. Start them first:\n  just dev   (terminal 1)\n  just frontend  (terminal 2)')
    process.exit(1)
  }
  try { await access(PRIMITIVES_DIR) }
  catch { console.error(`✗ No primitives folder at ${PRIMITIVES_DIR}`); process.exit(1) }

  const files = (await readdir(PRIMITIVES_DIR)).filter((f) => f.endsWith('.nadoc')).sort()
  if (!files.length) { console.error('✗ No .nadoc files in workspace/Primitives'); process.exit(1) }

  console.log(`Building previews for ${files.length} primitive(s)…`)
  const browser = await chromium.launch()
  let ok = 0
  try {
    for (const file of files) {
      try { if (await buildOne(browser, file)) ok++ }
      catch (e) { console.error(`  ✗ ${file}: ${e.message}`) }
    }
  } finally {
    await browser.close()
  }
  console.log(`Done: ${ok}/${files.length} previews generated in ${WORKSPACE_REL}/`)
}

await main()
