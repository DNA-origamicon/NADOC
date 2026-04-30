/**
 * MD panel — ball-and-stick rendering test.
 *
 * Verifies that:
 *   1. The #md-repr dropdown defaults to "nadoc" (not "ballstick").
 *   2. Switching to ball-and-stick, loading a real GROMACS run, and seeking
 *      frame 0 delivers a WebSocket frame message with a non-empty atoms array.
 *   3. atomisticRenderer.getMode() === 'ballstick' after frame delivery.
 *
 * Prerequisites:
 *   - Both servers running (playwright.config.js webServer stanzas cover this).
 *   - GROMACS run dir present at:
 *       /home/jojo/Work/NADOC/runs/10hb_bundle_params/nominal/
 *     with em.gro and view_whole.xtc files.
 *
 * Run:
 *   cd /home/jojo/Work/NADOC/frontend
 *   npx playwright test e2e/md_ballstick.spec.js --headed
 */

import { test, expect } from '@playwright/test'

const API       = 'http://127.0.0.1:8000/api'
const TOPO_PATH = '/home/jojo/Work/NADOC/runs/10hb_bundle_params/nominal/em.gro'
const XTC_PATH  = '/home/jojo/Work/NADOC/runs/10hb_bundle_params/nominal/view_whole.xtc'
const DESIGN_PATH = '/home/jojo/Work/NADOC/workspace/10hb.nadoc'
const LS_KEY    = 'nadoc_md_paths'

/**
 * Load the 10hb design and navigate the UI.
 *
 * Returns after the page is ready with the 10hb design loaded in the backend
 * and the splash screen dismissed. localStorage MD paths are set so that
 * _loadPersistedPaths() finds them on reload.
 */
async function bootWith10hb(page, request, mdPaths = null) {
  // Load 10hb design into the backend session.
  const r = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(r.ok(), 'POST /design/load for 10hb failed').toBeTruthy()

  // Navigate to the app (backend has 10hb in memory).
  await page.goto('/')
  await page.waitForSelector('#canvas')

  if (mdPaths) {
    // Set localStorage on the correct origin so _loadPersistedPaths() works.
    await page.evaluate(
      ([key, val]) => localStorage.setItem(key, val),
      [LS_KEY, JSON.stringify(mdPaths)]
    )
    // Reload so initMdPanel._loadPersistedPaths() picks up the stored paths.
    await page.reload()
    await page.waitForSelector('#canvas')
  }

  // Dismiss splash (design is already loaded, hide programmatically).
  await page.evaluate(() => {
    const splash = document.getElementById('splash-screen')
    if (splash) splash.style.display = 'none'
  })
}

/** Expand the MD panel (it starts collapsed). */
async function expandMdPanel(page) {
  const panelBody = page.locator('#md-panel-body')
  const isVisible = await panelBody.isVisible()
  if (!isVisible) {
    await page.click('#md-panel-heading')
    await expect(panelBody).toBeVisible()
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('MD panel — ball-and-stick', () => {

  test('repr dropdown defaults to nadoc', async ({ page, request }) => {
    await bootWith10hb(page, request)   // no mdPaths — test clean state
    await expandMdPanel(page)
    const reprSel = page.locator('#md-repr')
    await expect(reprSel).toBeVisible()
    const selected = await reprSel.evaluate(el => el.value)
    expect(selected).toBe('nadoc')
  })

  test('ball-and-stick frame delivers atoms array via WebSocket', async ({ page, request }) => {
    const mdPaths = { topoPath: TOPO_PATH, xtcPath: XTC_PATH }
    await bootWith10hb(page, request, mdPaths)
    await expandMdPanel(page)

    // Verify paths were restored from localStorage
    const topoName = page.locator('#md-topo-name')
    await expect(topoName).toContainText('em.gro', { timeout: 5_000 })
    const xtcName = page.locator('#md-xtc-name')
    await expect(xtcName).toContainText('view_whole.xtc')

    // Switch to ball-and-stick representation
    await page.selectOption('#md-repr', 'ballstick')

    // Intercept the WebSocket and capture the first frame message
    let capturedFrame = null
    const frameReceived = new Promise(resolve => {
      page.on('websocket', ws => {
        ws.on('framereceived', ev => {
          try {
            const msg = JSON.parse(ev.payload)
            if (msg.type === 'frame') {
              capturedFrame = msg
              resolve(msg)
            }
          } catch { /* ignore non-JSON */ }
        })
      })
    })

    // Click Load — requires both paths to be set
    const loadBtn = page.locator('#md-load-btn')
    await expect(loadBtn).not.toBeDisabled({ timeout: 5_000 })
    await loadBtn.click()

    // Wait up to 60 s for the backend to load the trajectory and send frame 0
    const frame = await Promise.race([
      frameReceived,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Timed out waiting for WS frame')), 60_000)
      ),
    ])

    // Validate frame payload
    expect(frame.type).toBe('frame')
    expect(Array.isArray(frame.atoms)).toBe(true)
    expect(frame.atoms.length).toBeGreaterThan(0)
    console.log(`frame 0: ${frame.atoms.length} heavy DNA atoms`)

    // Validate atomisticRenderer mode via window.__nadocTest
    const mode = await page.evaluate(() => window.__nadocTest?.getAtomisticRenderer?.()?.getMode())
    expect(mode).toBe('ballstick')
  })

  test('controls appear after load (metrics + scrubber)', async ({ page, request }) => {
    const mdPaths = { topoPath: TOPO_PATH, xtcPath: XTC_PATH }
    await bootWith10hb(page, request, mdPaths)
    await expandMdPanel(page)

    // Wait for a 'ready' WS message (signals controls should show)
    const readyReceived = new Promise(resolve => {
      page.on('websocket', ws => {
        ws.on('framereceived', ev => {
          try {
            const msg = JSON.parse(ev.payload)
            if (msg.type === 'ready') resolve(msg)
          } catch { /* ignore */ }
        })
      })
    })

    const loadBtn = page.locator('#md-load-btn')
    await expect(loadBtn).not.toBeDisabled({ timeout: 5_000 })
    await loadBtn.click()

    const ready = await Promise.race([
      readyReceived,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Timed out waiting for WS ready')), 60_000)
      ),
    ])

    expect(ready.n_frames).toBeGreaterThan(0)
    console.log(`ready: ${ready.n_frames} frames, ${ready.n_p_atoms} P-atoms`)

    // Controls div should now be visible
    await expect(page.locator('#md-controls')).toBeVisible({ timeout: 5_000 })
    await expect(page.locator('#md-scrubber')).toBeVisible()
    await expect(page.locator('#md-metrics-block')).toBeVisible()
  })
})
