/**
 * Smoke tests — basic UI and API functionality.
 *
 * These tests verify that the app loads correctly and core interactions work.
 * They require both servers to be running (playwright.config.js starts them
 * automatically via webServer, or reuses existing processes).
 */

import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors, loadScaffoldedPart } from './helpers/scene_harness.js'

// Read-only legacy fixture for renderer diagnosis: two helices and four crossovers.
// The fixture is never edited or republished by this test.
const SMOKE_DESIGN = '2hb_xover_val.nadoc'

// Backend base for the direct-API legs. Defaults to :8000; the isolated smoke
// config sets NADOC_E2E_API_BASE to its throwaway backend so these calls hit the
// test server, never the user's running one.
const API_BASE = process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000'

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Hover a CSS-based dropdown menu by menu label text, then click a dropdown item. */
async function openDropdownAndClick(page, menuLabel, itemId) {
  // CSS hover dropdowns require the mouse to be over the menu-item wrapper
  const menuItem = page.locator('.menu-item').filter({ hasText: menuLabel }).first()
  await menuItem.hover()
  await page.click(`#${itemId}`)
}

// ── App boot ────────────────────────────────────────────────────────────────

test.describe('App boot', () => {
  test('page title is NADOC 3D', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle('NADOC 3D')
  })

  test('fresh startup and reload do not show the selection tutorial toast', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('nadoc.hint.selModifiers.v1')
      window.__selectionStartupHintSeen = false
      new MutationObserver(() => {
        if ([...document.querySelectorAll('.toast-message')].some(el => el.textContent.includes('Selection: D = dimensions'))) {
          window.__selectionStartupHintSeen = true
        }
      }).observe(document, { childList: true, subtree: true, characterData: true })
    })
    await page.goto('/')
    for (let boot = 0; boot < 2; boot++) {
      await expect(page.locator('#canvas')).toBeVisible()
      await page.waitForFunction(() => !!window.__nadocTest)
      // The removed startup timer fired after 1500 ms. Observe beyond that
      // deadline, including transient toasts that might already have vanished.
      await page.waitForTimeout(2000)
      expect(await page.evaluate(() => window.__selectionStartupHintSeen)).toBe(false)
      if (boot === 0) await page.reload()
    }
  })

  test('Three.js canvas is visible', async ({ page }) => {
    await page.goto('/')
    const canvas = page.locator('#canvas')
    await expect(canvas).toBeVisible()
    // Canvas should have non-zero dimensions
    const box = await canvas.boundingBox()
    expect(box.width).toBeGreaterThan(100)
    expect(box.height).toBeGreaterThan(100)
  })

  test('menu bar is rendered with expected menus', async ({ page }) => {
    await page.goto('/')
    const menuBar = page.locator('#menu-bar')
    await expect(menuBar).toBeVisible()
    // Match only the top-level menu labels (direct children of #menu-bar) with
    // exact text — dropdowns contain nested .menu-item entries (e.g. "Edit…") that
    // would otherwise make a loose ".menu-item > button" match resolve to >1 element.
    for (const label of ['File', 'Edit', 'View']) {
      await expect(
        page.locator('#menu-bar > .menu-item > button').filter({ hasText: new RegExp(`^${label}$`) }),
      ).toBeVisible()
    }
  })

  test('mode indicator shows NADOC · WORKSPACE on load', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE')
  })

  test('welcome screen renders on boot', async ({ page }) => {
    await page.goto('/')
    // The welcome screen mounts the library panel (the primary New-Part entry point).
    await expect(page.locator('#welcome-screen')).toBeVisible()
    await expect(page.locator('#library-panel-mount')).toBeVisible()
  })
})

// ── File > New ───────────────────────────────────────────────────────────────
//
// The dialog chrome is now built by createModal(): the form fields live in the
// (un-hidden) #new-design-modal-body, the header title is .modal__title, and
// Cancel/Create are .modal__actions buttons addressed by accessible name. Name
// validation is inline (error text shown on empty submit), not button-disable.

test.describe('File > New Part dialog', () => {
  // "New Part" opens its modal in-place only when the current doc is empty; with
  // content it spawns a new tab (multi-document). Reset the server's active design
  // to empty before each test so New opens the modal here, deterministically,
  // regardless of what the dev server (or another spec) left loaded.
  test.beforeEach(async ({ page, request }) => {
    await request.post(`${API_BASE}/api/design`, {
      data: { name: 'smoke-reset', lattice_type: 'HONEYCOMB' },
    })
    await page.goto('/')
  })

  // The New-Part modal overlay, identified by the form body it contains.
  const modalOf = (page) =>
    page.locator('.modal__overlay').filter({ has: page.locator('#new-design-modal-body') })

  test('opens when File > New Part is clicked', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-modal-body')).toBeVisible()
    await expect(modalOf(page).locator('.modal__title')).toHaveText('New Part')
  })

  test('modal has a required name field', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-name')).toBeVisible()
    await expect(page.locator('#new-design-name')).toHaveValue('')
  })

  test('Create with an empty name shows a validation error', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const modal = modalOf(page)
    await modal.getByRole('button', { name: 'Create' }).click()
    // Inline validation: error shown, dialog stays open.
    await expect(page.locator('#new-design-name-error')).toBeVisible()
    await expect(page.locator('#new-design-modal-body')).toBeVisible()
  })

  test('shows Honeycomb and Square lattice options', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const body = page.locator('#new-design-modal-body')
    await expect(body).toContainText('Honeycomb')
    await expect(body).toContainText('Square')
  })

  test('Honeycomb radio is selected by default', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    const honeycombRadio = page.locator('input[name="new-lattice-type"][value="HONEYCOMB"]')
    await expect(honeycombRadio).toBeChecked()
  })

  test('Cancel closes the dialog', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await expect(page.locator('#new-design-modal-body')).toBeVisible()
    await modalOf(page).getByRole('button', { name: 'Cancel' }).click()
    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
  })

  test('Create dismisses the dialog and leaves the welcome screen', async ({ page }) => {
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', '__e2e__Test Part')
    await modalOf(page).getByRole('button', { name: 'Create' }).click()
    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
  })

  test('Create with Honeycomb closes the dialog and calls API with part name', async ({ page }) => {
    const apiCall = page.waitForRequest(req =>
      req.method() === 'POST' && /\/api\/design(\?|$)/.test(req.url())
    )

    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', '__e2e__My Honeycomb Part')
    await modalOf(page).getByRole('button', { name: 'Create' }).click()

    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
    const req = await apiCall
    expect(req.postDataJSON()?.name).toBe('__e2e__My Honeycomb Part')
  })

  test('Create with Square lattice fires API with SQUARE lattice type', async ({ page }) => {
    const apiCall = page.waitForRequest(req => req.method() === 'POST' && /\/api\/design(\?|$)/.test(req.url()))

    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.click('input[name="new-lattice-type"][value="SQUARE"]')
    await page.fill('#new-design-name', '__e2e__Square Test')
    await modalOf(page).getByRole('button', { name: 'Create' }).click()

    await expect(page.locator('#new-design-modal-body')).not.toBeVisible()
    expect((await apiCall).postDataJSON()?.lattice_type).toBe('SQUARE')
  })
})

// ── Command palette ──────────────────────────────────────────────────────────

test.describe('Command palette', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('opens with Ctrl+K', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()
    await expect(page.locator('#cmd-input')).toBeFocused()
  })

  test('closes with Escape', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await expect(page.locator('#cmd-palette-overlay')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.locator('#cmd-palette-overlay')).not.toBeVisible()
  })

  test('filters commands as user types', async ({ page }) => {
    await page.keyboard.press('Control+k')
    await page.fill('#cmd-input', 'scaffold')
    // Should show results matching "scaffold"
    const results = page.locator('#cmd-results')
    await expect(results).not.toBeEmpty()
  })
})

// ── API connectivity ─────────────────────────────────────────────────────────

test.describe('API', () => {
  test('GET /api/design returns a valid design', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/design`)
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    expect(body).toHaveProperty('design')
    expect(body.design).toHaveProperty('metadata')
    expect(body.design).toHaveProperty('helices')
    expect(body.design).toHaveProperty('strands')
  })

  test('POST /api/design creates a new empty design', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/design`, {
      data: { name: 'Playwright Test Design', lattice_type: 'HONEYCOMB' },
    })
    expect(resp.status()).toBe(201)
    const body = await resp.json()
    expect(body.design.metadata.name).toBe('Playwright Test Design')
    expect(body.design.helices).toHaveLength(0)
  })

  test('GET /api/design/geometry returns geometry data', async ({ request }) => {
    // First create a fresh design
    await request.post(`${API_BASE}/api/design`, {
      data: { name: 'geo-test', lattice_type: 'HONEYCOMB' },
    })
    const resp = await request.get(`${API_BASE}/api/design/geometry`)
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    // Geometry response shape: { helix_axes: [...], nucleotides: [...] }
    expect(body).toHaveProperty('helix_axes')
    expect(body).toHaveProperty('nucleotides')
  })
})

// ── Console-error gate (the main.js refactor commit gate) ─────────────────────
//
// This is the one check unit tests structurally cannot replace: it loads a real
// design and renders the full scene, asserting nothing throws. An extraction that
// breaks main()'s init order, subscription order, or closure scope surfaces here
// as an uncaught exception (pageerror) or console error — invisible to vitest.
//
// Run via `just smoke` before any main.js-touching commit.

test.describe('Console-error gate', () => {
  // Substrings of console-error messages that are known-benign environment noise,
  // NOT app regressions. Keep this list tight — every entry weakens the gate.
  const BENIGN = [
    'favicon.ico',          // browser auto-requests it; we don't ship one
    'WebSocket',            // ws may not be connected during a static smoke load
    'Failed to load resource', // covers the favicon 404 line in some browsers
  ]
  const isBenign = (text) => BENIGN.some((b) => text.includes(b))

  test('loads a real design and renders with zero console errors', async ({ page }) => {
    test.setTimeout(60_000)
    const consoleErrors = []
    const pageErrors = []
    page.on('console', (msg) => {
      if (msg.type() === 'error' && !isBenign(msg.text())) consoleErrors.push(msg.text())
    })
    page.on('pageerror', (err) => pageErrors.push(err.message))

    // Load through the app client after boot so both the document and frontend
    // store receive the fixture. A backend-only load leaves the welcome UI empty.
    const doc = '__e2e__smoke-render'
    const designPath = path.resolve(process.cwd(), '..', 'Examples', SMOKE_DESIGN)
    await page.goto(`/?doc=${doc}`)
    await expect(page.locator('#canvas')).toBeVisible()
    // Establish the editor host through File > New; loadDesign is a read-only
    // renderer fixture load and does not dismiss the welcome/menu shell itself.
    await openDropdownAndClick(page, 'File', 'menu-file-new')
    await page.fill('#new-design-name', '__e2e__smoke-render-host')
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
    await expect.poll(async () => (await page.request.get(`${API_BASE}/api/design`, { headers: { 'X-NADOC-Doc': doc } })).status()).toBe(200)
    await page.evaluate(async path => {
      const api = await import('/src/api/client.js')
      await api.loadDesign(path)
    }, designPath)
    // Give the geometry round-trip + renderer rebuild time to run and throw if broken.
    await page.waitForTimeout(1500)

    // Existing crossovers live outside the helix root. Both authoring tools must
    // dim their rendered materials and restore them on close without editing DNA.
    const arcDisplay = () => page.evaluate(() => {
      const root = window.__NADOC_DBG__.unfoldView.getArcRoot()
      return root.children.map(line => ({
        name: line.name, opacity: line.material.opacity,
        dimmed: line.material.customProgramCacheKey().includes('|nadoc-authoring-opacity'),
        depthWrite: line.material.depthWrite,
      }))
    })
    await expect.poll(async () => (await arcDisplay()).length).toBeGreaterThan(0)
    const originalArcs = await arcDisplay()
    for (const tool of ['extrude', 'sweep']) {
      await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
      await page.locator(`#menu-tools-${tool}`).click()
      await expect.poll(async () => {
        const arcs = await arcDisplay()
        return arcs.length > 0 && arcs.every(arc => arc.dimmed && !arc.depthWrite)
      }).toBe(true)
      await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
      await page.getByRole('button', { name: `Close ${tool === 'extrude' ? 'Extrude' : 'Sweep'}`, exact: true }).click()
      await expect.poll(arcDisplay).toEqual(originalArcs)
    }

    expect(pageErrors, `uncaught exceptions during load/render:\n${pageErrors.join('\n')}`).toEqual([])
    expect(consoleErrors, `console errors during load/render:\n${consoleErrors.join('\n')}`).toEqual([])
  })
})

// ── Teardown gate (close-session / reset) ─────────────────────────────────────
//
// Teardown is the gate's structural blind spot. The console-error gate above
// boots + renders but never TEARS DOWN, so a broken disposal escapes it — exactly
// how #34's `_assemblyMultiBox = null`-on-a-const TypeError shipped and threw on
// every assembly exit. This leg drives the design close-session path
// (`_closeSession` → `_resetForNewDesign` → `api.closeSession`), which disposes
// ~20 scene modules (photo mode, deform, slice plane, blunt ends, legends,
// representation reset, store-clear) and is otherwise never exercised by the suite.
//
// The sibling assembly-exit teardown (the #34 path itself) is covered by
// `assembly_exit_cleanup.spec.js`, which `just smoke` now also runs — kept as a
// separate file because building a 2-part assembly is heavier and reuses the
// scene_harness assembly builder. Both teardown paths are now IN the commit gate
// so neither can bit-rot out of CI the way out-of-gate specs do (#48).

test.describe('Teardown gate', () => {
  // Same benign-noise filter as the console-error gate (env noise, not regressions).
  const BENIGN = ['favicon.ico', 'WebSocket', 'Failed to load resource']
  const realErrors = (errs) => errs.filter((t) => !BENIGN.some((b) => t.includes(b)))

  test('Close Session from a loaded design tears down cleanly', async ({ page }) => {
    test.setTimeout(60_000)
    const errors = trackConsoleErrors(page)

    // A real loaded design in THIS tab's doc (a bare goto boots to welcome with an
    // empty random doc, which would take close-session's no-design short path and
    // skip `_resetForNewDesign`). loadScaffoldedPart goes through File>New in a
    // pinned doc, so `currentDesign` is set and the full teardown runs.
    await loadScaffoldedPart(page, { doc: 'smoke-close', name: 'close' })

    // Hold a display read past the working-popup threshold. Close must cancel it.
    let releaseGeometry
    const held = new Promise(resolve => { releaseGeometry = resolve })
    page.on('close', () => releaseGeometry())
    await page.route('**/api/design/geometry*', async route => {
      await held
      await route.fulfill({ json: { nucleotides: [], helix_axes: [] } }).catch(() => {})
    })
    const geometryFailed = page.waitForEvent('requestfailed', request => request.url().includes('/design/geometry'))
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      window.__closeGeometryDone = false
      api.getGeometry().then(() => { window.__closeGeometryDone = true })
    })
    await expect(page.locator('#op-progress')).toHaveClass(/visible/, { timeout: 8000 })

    // File → Close Session.
    await openDropdownAndClick(page, 'File', 'menu-file-close-session')

    // Returns to the welcome screen with the workspace mode indicator.
    await expect(page.locator('#mode-indicator')).toHaveText('NADOC · WORKSPACE', { timeout: 10_000 })
    await expect(page.locator('#welcome-screen')).toBeVisible()
    await geometryFailed
    await page.waitForFunction(() => window.__closeGeometryDone)
    expect(await page.evaluate(async () => {
      const { processLogSnapshot } = await import('/src/perf/process_log.js')
      return processLogSnapshot().entries.some(entry =>
        entry.label === 'GET /design/geometry' && entry.status === 'Cancelled')
    })).toBe(true)
    await expect(page.locator('#op-progress')).not.toHaveClass(/visible/)
    await expect(page.locator('[data-role="design-readiness"]')).toBeHidden()
    const closed = await page.request.get('/api/design', { headers: { 'X-NADOC-Doc': 'smoke-close' } })
    expect(closed.status()).toBe(404)
    releaseGeometry()
    await page.unroute('**/api/design/geometry*')
    // Covers the readiness polling interval and reloading the same document URL.
    await page.waitForTimeout(10_500)
    await expect(page.locator('[data-role="design-readiness"]')).toBeHidden()
    await page.reload()
    await page.waitForFunction(() => !!window.__nadocTest)
    await expect(page.locator('#welcome-screen')).toBeVisible()
    await expect(page.locator('[data-role="design-readiness"]')).toBeHidden()
    await expect(page.locator('#op-progress')).not.toHaveClass(/visible/)

    const real = realErrors(errors)
    expect(real, `console/page errors during close-session teardown:\n${real.join('\n')}`).toEqual([])
  })
})

// Experimental routing is covered only in the isolated smoke launcher.
import './helpers/experimental_autostaple.js'

// Persistence: job responses are intercepted; no solver, authored structure or
// job file is created. Browser state dies with the context; the isolated smoke
// launcher removes its workspace, caches, credentials and reports on failure too.
test('SNUPI Stop is hidden idle and disappears when the running job finishes', async ({ page }) => {
  let jobs = []
  await page.route(/\/api\/snupi\/jobs(?:\?.*)?$/, route => route.fulfill({ json: jobs }))
  await page.route('**/api/snupi/jobs/__e2e__stop/progress', route => route.fulfill({ json: { overall: 0.5 } }))
  await page.goto('/?doc=__e2e__snupi_stop')
  await page.waitForFunction(() => !!window.__nadocTest)
  // Expose the real engine panel without authoring a design or running a solver.
  await page.evaluate(async () => {
    const panel = document.getElementById('snupi-jobs-panel')
    // Simulate reparents the run controls outside the engine's detail panel.
    for (const root of [panel, document.getElementById('snupi-stop-row').parentElement]) {
      for (let node = root; node && node !== document.body; node = node.parentElement) {
        node.hidden = false
        node.classList.remove('hidden')
        node.style.display = 'block'
      }
    }
    window.__stopPanel = (await import('/src/ui/snupi_jobs_panel.js')).initSnupiJobsPanel({ getWorkspacePath: () => '__e2e__stop.nadoc' })
    await window.__stopPanel.refresh()
  })
  const stop = page.locator('#snupi-jobs-stop-btn')
  await expect(stop).toBeHidden()
  jobs = [{ job_id: '__e2e__stop', design_source_path: '__e2e__stop.nadoc', status: 'running', stages: [] }]
  await page.evaluate(() => window.__stopPanel.refresh())
  await expect(stop).toBeVisible()
  await expect(stop).toBeEnabled()
  jobs = [{ job_id: '__e2e__stop', design_source_path: '__e2e__stop.nadoc', status: 'completed', stages: [] }]
  await page.evaluate(() => window.__stopPanel.refresh())
  await expect(stop).toBeHidden()
  await expect(stop).toBeDisabled()
  await page.evaluate(() => window.__stopPanel.dispose())
})

// Telemetry-only app exercise: no structures/jobs/pods are created. Browser state
// is discarded, and the smoke launcher removes workspace/cache/report output.
test('RunPod SNUPI bar uses dynamics counters and labels pending or stale telemetry', async ({ page }) => {
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [] }))
  await page.goto('/?doc=__e2e__snupi_progress')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(() => {
    for (let node = document.getElementById('simulate-jobs-progress'); node && node !== document.body; node = node.parentElement) {
      node.hidden = false
      node.classList.remove('hidden')
      node.style.display = 'block'
    }
  })
  const report = async fields => page.evaluate(fields => {
    window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed', { detail: { select: true,
      node: { engine: 'snupi', dynamics: true, job_id: '__e2e__progress', design_name: 'Telemetry',
        execution_target: 'runpod', status: 'running', n_steps: 20, total_steps: 60000, stages: [], ...fields } } }))
  }, fields)
  const status = page.locator('#simulate-jobs-status')
  const bar = page.locator('#simulate-jobs-progress .bar')
  const stage = id => page.locator(`#snupi-jobs-timeline [data-stage="${id}"]`)
  await report({ phase: 'RunPod · Calculating stable dynamics timestep', current_step: 0, progress_indeterminate: true })
  await expect(status).toContainText('Dynamics pending · 60,000 steps planned')
  await expect(status).toContainText('Calculating stable dynamics timestep')
  await expect(stage('stiffness')).toHaveAttribute('data-status', 'done')
  await expect(stage('timestep')).toHaveAttribute('aria-current', 'step')
  await expect(stage('integration')).toHaveAttribute('data-status', 'pending')
  expect(await bar.evaluate(el => getComputedStyle(el).animationName)).toBe('prep-progress-stripes')
  await report({ phase: 'RunPod · trajectory', current_step: 30000, progress_fraction: .55, progress_indeterminate: false })
  await expect(status).toContainText('50% dynamics · 30,000 / 60,000 steps · 30,000 left')
  expect(await bar.evaluate(el => el.style.width)).toBe('50%')
  await expect(stage('integration')).toHaveAttribute('aria-current', 'step')
  await expect(stage('integration')).toContainText('30,000 / 60,000 steps')
  await expect(stage('analysis')).toHaveAttribute('data-status', 'pending')
  expect(await bar.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
  await report({ phase: 'RunPod · trajectory', current_step: 30000, progress_last_known: true })
  await expect(status).toContainText('last known (sync unavailable)')
  await expect(stage('integration')).toHaveAttribute('data-status', 'last-known')
  await report({ phase: 'RunPod · Analyzing dynamics trajectory', current_step: 60000 })
  await expect(stage('integration')).toHaveAttribute('data-status', 'done')
  await expect(stage('analysis')).toHaveAttribute('aria-current', 'step')
  await report({ phase: 'RunPod · Downloading results', current_step: 60000 })
  await expect(stage('analysis')).toHaveAttribute('data-status', 'done')
  await expect(stage('download')).toHaveAttribute('aria-current', 'step')
  await report({ status: 'completed', current_step: 60000 })
  await expect(status).toContainText('completed')
  await expect(stage('download')).toHaveAttribute('data-status', 'done')
  expect(await bar.evaluate(el => el.style.width)).toBe('100%')
})

// Persistence inventory: intercepted telemetry only, no structures or remote
// launches. Browser context and the isolated launcher's entire scratch root are
// removed on failure as well as success.
test('solver tabs show activity and selected remote jobs populate the Clusters card', async ({ page }) => {
  let active = ['snupi', 'cando', 'mrdna'].map(engine => ({ engine, status: 'running' }))
  await page.route('**/api/jobs/active**', route => route.fulfill({ json: { jobs: active } }))
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [] }))
  await page.route('**/api/runpod/status', route => route.fulfill({ json: { connected: false } }))
  await page.route('**/api/solver-cluster/runpod-check', route => route.fulfill({ json: { ok: false, checks: [] } }))
  for (const engine of ['snupi', 'mrdna']) {
    const job = { job_id: `__e2e__${engine}_provider`, design_source_path: '__e2e__provider.nadoc',
      status: 'running', stages: [], execution_target: 'runpod',
      remote: { pod_id: 'review-pod', scheduler_state: 'RUNNING', settings: { gpu_id: 'RTX 4090', mem_gb: 75, cores: 8, quoted_rate: .89, budget_usd: 5 } } }
    await page.route(new RegExp(`/api/${engine}/jobs(?:\\?.*)?$`), route => route.fulfill({ json: [job] }))
    await page.route(`**/api/${engine}/jobs/${job.job_id}/progress`, route => route.fulfill({ json: { overall: 0 } }))
  }
  await page.goto('/?doc=__e2e__provider')
  await page.waitForFunction(() => !!window.__nadocTest)
  for (const engine of ['snupi', 'cando', 'mrdna']) {
    const spinner = page.locator(`[data-engine-spinner="${engine}"]`)
    await expect(spinner).toHaveJSProperty('hidden', false)
    expect(await spinner.evaluate(el => getComputedStyle(el).animationName)).not.toBe('none')
  }
  for (const engine of ['snupi', 'mrdna']) {
    await page.evaluate(engine => {
      const showAll = document.getElementById(`${engine}-jobs-show-all`)
      showAll.checked = true
      showAll.dispatchEvent(new Event('change'))
      for (let node = document.getElementById(`${engine}-jobs-list`); node && node !== document.body; node = node.parentElement) {
        node.hidden = false; node.classList.remove('hidden'); node.style.display = 'block'
      }
    }, engine)
    await page.locator(`#${engine}-run-target-local`).check({ force: true })
    await page.locator(`#${engine}-jobs-list [data-job-id="__e2e__${engine}_provider"]`).dispatchEvent('click')
    await expect(page.locator(`#${engine}-run-target-runpod`)).toBeChecked()
    await expect(page.locator(`#${engine}-jobs-runpod-pane`)).toHaveJSProperty('hidden', false)
    await expect(page.locator(`#${engine}-runpod-selected-job`)).toContainText('review-pod')
    await expect(page.locator(`#${engine}-runpod-selected-job`)).toContainText('RTX 4090')
    await expect(page.locator(`#${engine}-runpod-mem_gb`)).toHaveValue('75')
  }
  active = []
  for (const engine of ['snupi', 'cando', 'mrdna']) {
    await expect(page.locator(`[data-engine-spinner="${engine}"]`)).toHaveJSProperty('hidden', true, { timeout: 12000 })
  }
})
