/**
 * Reusable scene-gesture harness for WebGL e2e.
 *
 * Robust pattern (validated empirically + by research): drive a REAL synthetic
 * click through the app's REAL raycast, assert on EXPOSED STATE (`__nadocTest`),
 * and RETRY on miss. Retry is the load-bearing part: at integer pixel precision a
 * click on a small WebGL bead lands only ~half the time, so "project a point and
 * click once" is flaky — you click candidates until the state actually changes.
 *
 * `__nadocTest.pickBeadAt(x,y)` is the occlusion-correct identity oracle (the real
 * raycast — "what is front-most here?"); `getSelectedObject` / `getCtrlBeadCount`
 * are the state oracles the retry loop checks. Tier 1 (logic) lives in vitest;
 * this is Tier 2 (real interaction). Tier 3 (golden-image "does it look right")
 * is intentionally NOT here — it needs a pinned software rasterizer + per-platform
 * baselines we don't yet run in CI.
 */
import { expect } from '@playwright/test'

// Backend base URL. Defaults to the user's dev server (:8000) for ad-hoc spec
// runs; the isolated smoke config sets NADOC_E2E_API_BASE to its throwaway
// backend so the gate never touches the user's running server.
const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000') + '/api'

/**
 * Collect browser console errors + uncaught page errors into an array.
 *
 * The stateful-extraction "one app exercise" gate is, at minimum, "drive the
 * feature and assert zero console errors". Every throwaway exercise spec opened
 * with the same three lines; this centralizes them.
 *
 *   const errors = trackConsoleErrors(page)
 *   ... exercise the feature ...
 *   expect(errors, errors.join('\n')).toEqual([])
 *
 * @param {import('@playwright/test').Page} page
 * @returns {string[]} live array, appended to as errors occur
 */
export function trackConsoleErrors(page) {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))
  return errors
}

/**
 * Boot on a PINNED ?doc, create a part, build a scaffolded 200-bp helix in that
 * same backend doc (so page.request and the tab agree — multi-doc), nudge a
 * rebuild, wait for backbone beads, then zoom past cylinder-LOD so beads are
 * full-scale + pickable. Returns once the scene has pickable beads.
 */
export async function loadScaffoldedPart(page, { doc, name = 'harness', extraQuery = '' }) {
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await page.goto(`/?doc=${doc}${extraQuery}`)
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  // `__e2e__` prefix → global-teardown removes the auto-saved workspace file.
  await page.fill('#new-design-name', `__e2e__${name}`)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })

  // The welcome screen hides as soon as the PAGE has a design — but File→New's
  // POST may still be in flight, and on a cold smoke backend it can take >500 ms.
  // A fixed sleep here raced it: page.request then hit the backend before the doc
  // had a design and got 404 "No active design", so every downstream call fell
  // apart. Poll the backend's own view of THIS doc instead of guessing a duration.
  await expect.poll(
    async () => (await page.request.get(`${API}/design`, { headers: H })).status(),
    { timeout: 15_000, message: `backend never got a design for doc ${doc}` },
  ).toBe(200)

  await page.request.post(`${API}/design/helix-at-cell`, { data: { row: 0, col: 0, length_bp: 200 }, headers: H })
  // Scaffold the helix by painting a domain over its full length. (There is no
  // POST /design/auto-scaffold — e9d6750 consolidated it into the -seamed/-seamless
  // variants and never updated this helper, so that call had been 405-ing into this
  // path for weeks. Painting directly is what has actually been running; keep it.)
  const { design } = await (await page.request.get(`${API}/design`, { headers: H })).json()
  await page.request.post(`${API}/design/scaffold-domain-paint`, {
    data: { helix_id: design.helices[0].id, lo_bp: 0, hi_bp: 199 }, headers: H,
  })
  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: d })
    bc.close()
  }, doc)

  await page.waitForFunction(() => {
    const s = window.__nadocTest?.scene
    if (!s) return false
    let ok = false
    s.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 20_000 })
  await page.waitForTimeout(300)

  const box = await page.locator('#canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 10; i++) await page.mouse.wheel(0, -120)
  await page.waitForTimeout(600)
}

/**
 * Candidate bead client points: projected centres, with points under the menu bar
 * or side panels removed (those overlay the full-width canvas, so a click there
 * never reaches it), sorted by proximity to canvas centre (most reliably hittable
 * first). The retry loops below click through these until the state changes.
 */
export async function beadCandidates(page) {
  const box = await page.locator('#canvas').boundingBox()
  const pts = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(80))
  const rects = []
  for (const sel of ['#menu-bar', '#left-panel', '#right-panel']) {
    const b = await page.locator(sel).boundingBox().catch(() => null)
    if (b) rects.push(b)
  }
  const covered = (p) => rects.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height)
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2
  return pts.filter(p => !covered(p)).sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy))
}

// NOTE on plain-click strand selection: selection_manager gates regular-click
// selection by `selectableTypes` (set via the filter UI), so a bare bead click
// won't select a strand in a default/fresh part. The Alt-click measurement-bead
// pick below is NOT gated, so it's the reliable primitive to build gesture tests
// on (and `getSelectedObject` is exposed for specs that first enable a filter).

/**
 * Alt-pick distinct beads until exactly `n` measurement beads are registered.
 * A missed Alt-click clears the set (selection_manager behaviour), so reset and
 * keep going — this state-feedback retry is what makes tiny-target clicking reliable.
 * Returns the final ctrl-bead count.
 */
export async function altPickBeads(page, n = 2) {
  const cands = await beadCandidates(page)
  let count = 0
  const used = []
  for (const b of cands) {
    if (used.some(u => Math.hypot(u.x - b.x, u.y - b.y) < 20)) continue
    await page.keyboard.down('Alt')
    await page.mouse.click(b.x, b.y)
    await page.keyboard.up('Alt')
    await page.waitForTimeout(120)
    const c = await page.evaluate(() => window.__nadocTest.getCtrlBeadCount())
    if (c > count) used.push(b); else used.length = 0
    count = c
    if (count === n) break
  }
  return count
}

/**
 * Engage the End selection level (real filter button), then multi-select a valid
 * forced-ligation pair — one 5′ end + one 3′ end on DIFFERENT strands — with the
 * NORMAL selection gesture the user named first: a Ctrl-drag LASSO over the ends
 * (same end-bead set that Shift-click / Ctrl-click feed). A lasso is a single,
 * pixel-precision-free gesture, so it's far more reliable than clicking a small
 * WebGL bead.
 *
 * `getEndBeadScreenPositions()` gives on-screen end beads with polarity + strand
 * id, so we choose the CLOSEST valid pair whose tight bounding box contains no
 * OTHER end (→ the lasso captures exactly those two), then Ctrl-drag that box.
 * Returns { count, five, three } — the identities selected (for assertion).
 */
export async function selectEndsForLigation(page) {
  await page.click('#select-filter .sf-btn[data-key="ends"]')
  await page.waitForFunction(() => window.__nadocTest.getSelectionLevel() === 'end', null, { timeout: 4000 })

  const iw = await page.evaluate(() => window.innerWidth)
  const panels = []
  for (const sel of ['#menu-bar', '#left-panel', '#right-panel']) {
    const b = await page.locator(sel).boundingBox().catch(() => null)
    if (b) panels.push(b)
  }
  const covered = (p) => p.x > iw - 305 || panels.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height)

  const ends = (await page.evaluate(() => window.__nadocTest.getEndBeadScreenPositions())).filter(e => !covered(e))
  const fives  = ends.filter(e => e.is_five_prime  && !e.is_three_prime)
  const threes = ends.filter(e => e.is_three_prime && !e.is_five_prime)
  // Closest valid cross-strand pair first: a small box that a lasso can enclose
  // without sweeping in a third end.
  const pairs = []
  for (const f of fives) for (const t of threes) {
    if (f.strand_id !== t.strand_id) pairs.push({ five: f, three: t, d: Math.hypot(f.x - t.x, f.y - t.y) })
  }
  pairs.sort((a, b) => a.d - b.d)

  const count = () => page.evaluate(() => window.__nadocTest.getCtrlBeadCount())

  for (const pair of pairs) {
    // A padded box around just this pair; skip if any OTHER end sits inside it
    // (the lasso would grab a third, breaking the exactly-two-ends requirement).
    const pad = 12
    const x1 = Math.min(pair.five.x, pair.three.x) - pad, x2 = Math.max(pair.five.x, pair.three.x) + pad
    const y1 = Math.min(pair.five.y, pair.three.y) - pad, y2 = Math.max(pair.five.y, pair.three.y) + pad
    const contaminated = ends.some(e => e !== pair.five && e !== pair.three && e.x >= x1 && e.x <= x2 && e.y >= y1 && e.y <= y2)
    if (contaminated) continue

    // Ctrl-drag a lasso across the box (down at one corner → move past the 4px
    // threshold → up at the far corner). The end filter is engaged, so the lasso
    // captures the enclosed 5′/3′ ends into the end-bead set (_finalizeLasso).
    await page.keyboard.down('Control')
    await page.mouse.move(x1, y1)
    await page.mouse.down()
    await page.mouse.move((x1 + x2) / 2, (y1 + y2) / 2, { steps: 3 })
    await page.mouse.move(x2, y2, { steps: 3 })
    await page.mouse.up()
    await page.keyboard.up('Control')
    await page.waitForTimeout(200)

    if ((await count()) === 2) return { count: 2, five: pair.five, three: pair.three }
    // Reset before the next candidate (Escape clears a non-empty end-bead set).
    if ((await count()) > 0) { await page.keyboard.press('Escape'); await page.waitForTimeout(100) }
    if ((await page.evaluate(() => window.__nadocTest.getSelectionLevel())) !== 'end') {
      await page.click('#select-filter .sf-btn[data-key="ends"]')
      await page.waitForFunction(() => window.__nadocTest.getSelectionLevel() === 'end', null, { timeout: 4000 })
    }
  }
  return { count: await count() }
}

/** Nearest integer pixel to a target end whose front-most bead (real raycast) IS
 *  that exact end (helix/bp/direction); null if none within the ring. */
async function _verifiedEndPixel(page, target) {
  return page.evaluate(({ t }) => {
    for (let r = 0; r <= 8; r++) {
      for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue
        const x = Math.round(t.x) + dx, y = Math.round(t.y) + dy
        const h = window.__nadocTest.pickBeadAt(x, y)
        if (h && h.helix_id === t.helix_id && h.bp_index === t.bp_index && h.direction === t.direction) return { x, y }
      }
    }
    return null
  }, { t: target })
}

/**
 * The exact bug scenario: at End level, PLAIN-click one end (→ single selection),
 * then CTRL-click a different-strand opposite-polarity end. Correct behavior folds
 * the plain-clicked end into the end-bead set too, so BOTH count (getCtrlBeadCount
 * === 2). Picks the farthest valid pair (>80px apart) so each click resolves its
 * own end. Returns { count, five, three, afterPlain } (afterPlain = the single
 * selection recorded by the plain click, for assertion).
 */
export async function selectEndsPlainThenCtrl(page) {
  await page.click('#select-filter .sf-btn[data-key="ends"]')
  await page.waitForFunction(() => window.__nadocTest.getSelectionLevel() === 'end', null, { timeout: 4000 })

  const iw = await page.evaluate(() => window.innerWidth)
  const panels = []
  for (const sel of ['#menu-bar', '#left-panel', '#right-panel']) {
    const b = await page.locator(sel).boundingBox().catch(() => null)
    if (b) panels.push(b)
  }
  const covered = (p) => p.x > iw - 305 || panels.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height)

  const ends = (await page.evaluate(() => window.__nadocTest.getEndBeadScreenPositions())).filter(e => !covered(e))
  const fives  = ends.filter(e => e.is_five_prime  && !e.is_three_prime)
  const threes = ends.filter(e => e.is_three_prime && !e.is_five_prime)
  const pairs = []
  for (const f of fives) for (const t of threes) {
    if (f.strand_id !== t.strand_id) pairs.push({ five: f, three: t, d: Math.hypot(f.x - t.x, f.y - t.y) })
  }
  pairs.sort((a, b) => b.d - a.d)   // farthest first → distinct clicks

  const count = () => page.evaluate(() => window.__nadocTest.getCtrlBeadCount())

  for (const pair of pairs) {
    if (pair.d < 12) continue   // essentially the same bead on screen — skip
    const p5 = await _verifiedEndPixel(page, pair.five)
    const p3 = await _verifiedEndPixel(page, pair.three)
    if (!p5 || !p3 || (p5.x === p3.x && p5.y === p3.y)) continue

    // PLAIN click the 5′ end → single selection (selectedObject), no ctrl-beads yet.
    await page.mouse.click(p5.x, p5.y)
    await page.waitForTimeout(120)
    const afterPlain = await page.evaluate(() => window.__nadocTest.getSelectedObject())

    // CTRL-click the 3′ end → must fold the plain end in AND add this one → 2.
    await page.keyboard.down('Control')
    await page.mouse.click(p3.x, p3.y)
    await page.keyboard.up('Control')
    await page.waitForTimeout(150)

    if ((await count()) === 2) return { count: 2, five: pair.five, three: pair.three, afterPlain }
    // Reset and try another pair.
    if ((await count()) > 0) { await page.keyboard.press('Escape'); await page.waitForTimeout(100) }
    if ((await page.evaluate(() => window.__nadocTest.getSelectionLevel())) !== 'end') {
      await page.click('#select-filter .sf-btn[data-key="ends"]')
      await page.waitForFunction(() => window.__nadocTest.getSelectionLevel() === 'end', null, { timeout: 4000 })
    }
  }
  return { count: await count() }
}

// ── Assembly gesture harness ───────────────────────────────────────────────
// The design-view helpers above pick backbone BEADS. The assembly canvas
// pointer handlers (_onAssemblyPointerDown / _onAssemblyClick) instead pick
// part INSTANCES, so these helpers build a rendered multi-part assembly and
// drive instance selection through the real raycast + state oracles (same
// robust pattern: pick → click → assert exposed state → retry on miss).

/**
 * Build a rendered multi-part assembly in a PINNED doc and enter assembly mode.
 *
 * The existing inline `MINIMAL_DESIGN` fixture (assembly_gizmo.spec.js) renders
 * NOTHING — empty helices, so its instances have no pickable body and that spec
 * selects via the panel row. For a canvas-gesture test we need real geometry,
 * so this reuses `loadScaffoldedPart` to build a 200-bp design, captures it via
 * the API, then adds it as `n` inline instances (offset on Y so their screen
 * centres are distinct). Pressing `a` enters assembly mode → the pointer
 * handlers attach and `_runAssemblyRebuild` fits the camera to the parts.
 *
 * Returns the instance ids in add order.
 */
export async function loadAssemblyWithParts(page, { doc, n = 2, name = 'asm' }) {
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  // Force the per-instance renderer (?shared=0): it builds inline-source designs
  // into a pickable cache, so pickInstance / getInstanceCenters work. The shared
  // GPU path doesn't materialize a freshly-built inline design's geometry. The
  // pointer HANDLERS under test (_onAssemblyClick / _onAssemblyPointerDown) call
  // assemblyRenderer.pickInstance regardless of path, so this faithfully gates
  // their selection wiring — only the renderer's pick implementation differs.
  await loadScaffoldedPart(page, { doc, name, extraQuery: '&shared=0' })
  // Save the built design to a workspace file and reference it as a FILE source.
  // A freshly-built INLINE design doesn't reliably materialize geometry in the
  // renderer; the file path goes through the server's standard geometry pipeline
  // (load topology → derive B-DNA geometry), which is the app's real assembly
  // case and renders reliably. `__e2e__` prefix → global-teardown removes it.
  const partRel = `__e2e__${name}_part.nadoc`
  await page.request.post(`${API}/design/save`, { data: { path: `workspace/${partRel}` }, headers: H })
  await page.request.post(`${API}/assembly`, { data: { name: `__e2e__${name}` }, headers: H })
  const ids = []
  for (let i = 0; i < n; i++) {
    // Row-major 4×4: translate on X by 25·i nm (last entry of row 0). Enough to
    // separate the two thin rods on screen, small enough that both stay in view
    // when the camera frames close (needed so the thin rods are fat targets).
    const transform = { values: [1, 0, 0, 25 * i, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] }
    const r = await page.request.post(`${API}/assembly/instances`, {
      data: { source: { type: 'file', path: partRel }, name: `Part ${i + 1}`, transform }, headers: H,
    })
    const body = await r.json()
    // The doc-scoped path returns the .nass v2 wire format (instances_v2 +
    // deduped sources); the legacy default-doc path returns instances.
    const insts = body?.assembly?.instances_v2 ?? body?.assembly?.instances
    if (!Array.isArray(insts) || !insts.length) {
      throw new Error(`add-instance ${r.status()} asmKeys=${Object.keys(body.assembly ?? {}).join(',')}`)
    }
    ids.push(insts[insts.length - 1].id)
  }
  await _enterAssemblyAndFrame(page)
  return ids
}

/**
 * Enter assembly mode and converge on a STABLE camera framing where the parts
 * are pickable. The renderer's bounding box is empty for these instances, so
 * the assembly's auto-fit can't frame the camera AND fires late (drifting it
 * off); we frame deterministically on the rendered geometry and require two
 * consecutive fine scans to see clickable parts (the rods are thin, so a coarse
 * scan steps over them — see assemblyInstanceCandidates). Throws if never stable.
 */
async function _enterAssemblyAndFrame(page) {
  await page.evaluate(() => window.__nadocTest.enterAssemblyMode())
  await expect(page.locator('#mode-indicator')).toContainText('ASSEMBLY', { timeout: 10_000 })
  for (let t = 0; t < 24; t++) {
    await frameAssembly(page)
    await page.waitForTimeout(400)
    if ((await assemblyInstanceCandidates(page)).length) {
      await page.waitForTimeout(400)
      if ((await assemblyInstanceCandidates(page)).length) return
    }
  }
  throw new Error('assembly instances never became stably pickable (framing / geometry)')
}

/** Deterministically aim the camera at the assembly instances (the auto-fit
 *  can't, and may drift the camera off them). Call before any gesture so a late
 *  auto-fit can't leave the parts off-screen. */
export async function frameAssembly(page) {
  await page.evaluate(() => window.__nadocTest.frameAssemblyForTest?.())
  await page.waitForTimeout(120)
}

/** Bounding rects of the overlays that sit above the full-width canvas. */
async function _overlayRects(page) {
  const rects = []
  for (const sel of ['#menu-bar', '#left-panel', '#right-panel', '#assembly-panel']) {
    const b = await page.locator(sel).boundingBox().catch(() => null)
    if (b) rects.push(b)
  }
  return rects
}

/**
 * Grid-scan the canvas with the REAL raycast (`pickAssemblyInstanceAt`) and
 * return one client point per pickable instance — the point closest to canvas
 * centre (most reliably re-hittable). Renderer-agnostic: works wherever
 * pickInstance does, without depending on getInstanceCenters (which is empty on
 * the shared path and, for freshly-built inline designs, on the per-instance
 * path too). Points under the menu bar / side panels are excluded.
 */
export async function assemblyInstanceCandidates(page) {
  const box = await page.locator('#canvas').boundingBox()
  const panels = await _overlayRects(page)
  return page.evaluate(({ b, panels }) => {
    const covered = (x, y) => panels.some(r => x >= r.x && x <= r.x + r.width && y >= r.y && y <= r.y + r.height)
    const cx = b.x + b.width / 2, cy = b.y + b.height / 2
    const best = {}
    // FINE grid: instances render as thin rods (~2 nm wide); a coarse grid steps
    // over them. The scan runs in-browser (cheap raycasts), so density is free.
    for (let fy = 0.1; fy <= 0.9; fy += 0.015) {
      for (let fx = 0.05; fx <= 0.95; fx += 0.015) {
        const x = b.x + b.width * fx, y = b.y + b.height * fy
        if (covered(x, y)) continue
        const h = window.__nadocTest.pickAssemblyInstanceAt(x, y)
        if (!h) continue
        const dc = Math.hypot(x - cx, y - cy)
        if (!best[h.id] || dc < best[h.id].dc) best[h.id] = { x, y, dc }
      }
    }
    return Object.entries(best).map(([id, p]) => ({ id, x: p.x, y: p.y }))
  }, { b: box, panels })
}

/**
 * Find the nearest INTEGER pixel to (cx,cy) at which the real pick resolves an
 * instance (matching `want` if given), searching outward in rings. The clicked
 * pixel must equal the pre-checked pixel — instances render as thin rods, so a
 * float candidate rounded to the click's integer pixel can miss by 1px.
 */
async function _pixelForInstance(page, cx, cy, want) {
  return page.evaluate(({ cx, cy, want }) => {
    for (let r = 0; r <= 10; r++) {
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue   // ring only
          const x = Math.round(cx) + dx, y = Math.round(cy) + dy
          const h = window.__nadocTest.pickAssemblyInstanceAt(x, y)
          if (h && (!want || h.id === want)) return { x, y, id: h.id }
        }
      }
    }
    return null
  }, { cx, cy, want })
}

/**
 * Click a part instance on the canvas until it becomes the active instance.
 * Locates an exact pickable integer pixel (ring search) so the click hits the
 * same pixel the pick confirmed. Pass `{id}` to target a specific instance,
 * else any. Returns the active id.
 */
export async function selectAssemblyInstance(page, { id = null } = {}) {
  await frameAssembly(page)
  const cands = await assemblyInstanceCandidates(page)
  const targets = id ? cands.filter(c => c.id === id) : cands
  for (const c of targets) {
    const px = await _pixelForInstance(page, c.x, c.y, id)
    if (!px) continue
    await page.mouse.click(px.x, px.y)
    await page.waitForTimeout(250)
    const active = await page.evaluate(() => window.__nadocTest.getActiveInstanceId())
    if (active && (!id || active === id)) return active
  }
  return page.evaluate(() => window.__nadocTest.getActiveInstanceId())
}

/**
 * Click a point on the canvas that the real pick reports as EMPTY (no instance),
 * avoiding the menu bar, side panels, and the bottom-left ✓ confirm button.
 * Used to assert that an empty click clears the assembly selection.
 */
export async function clickEmptyAssemblySpace(page) {
  const box = await page.locator('#canvas').boundingBox()
  const rects = []
  for (const sel of ['#menu-bar', '#left-panel', '#right-panel', '#assembly-panel']) {
    const b = await page.locator(sel).boundingBox().catch(() => null)
    if (b) rects.push(b)
  }
  const covered = (p) => rects.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height)
  // Scan a coarse grid, skip the top 50px (menu) and bottom 70px (confirm btn).
  for (let fy = 0.25; fy <= 0.75; fy += 0.15) {
    for (let fx = 0.08; fx <= 0.5; fx += 0.12) {
      const p = { x: box.x + box.width * fx, y: box.y + box.height * fy }
      if (p.y < box.y + 50 || p.y > box.y + box.height - 70) continue
      if (covered(p)) continue
      const hit = await page.evaluate(([X, Y]) => window.__nadocTest.pickAssemblyInstanceAt(X, Y), [p.x, p.y])
      if (!hit) { await page.mouse.click(p.x, p.y); await page.waitForTimeout(400); return p }
    }
  }
  return null
}

/**
 * Build a single-instance assembly whose part has a CLUSTER carrying a revolute
 * CLUSTER-JOINT, with the instance flagged `allow_part_joints`. This is the
 * fixture for the part-joint ring-drag gesture (Priority 2b in
 * _onAssemblyPointerDown → _partJointDrag → _updatePartJointDrag, which builds
 * the revolute world-delta via gear_math.rotationDeltaMatrix). The joint axis is
 * +Y so it faces the broad-face framing camera (ring in the XZ plane → screen
 * drags map to a clean angle). Returns { instanceId, clusterId }.
 */
export async function loadAssemblyWithClusterJoint(page, { doc, name = 'pjoint' }) {
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name, extraQuery: '&shared=0' })
  const helixId = (await (await page.request.get(`${API}/design`, { headers: H })).json())
    .design.helices[0].id
  // Cluster owning the (only) helix → rotating it rotates the whole part.
  const cl = await (await page.request.post(`${API}/design/cluster`, {
    data: { name: 'pj', helix_ids: [helixId] }, headers: H,
  })).json()
  const clusters = cl.design.cluster_transforms
  const clusterId = clusters[clusters.length - 1].id
  // Revolute joint, axis +Y through the rod mid-point.
  await page.request.post(`${API}/design/cluster/${clusterId}/joint`, {
    data: { axis_origin: [0, 0, 33], axis_direction: [0, 1, 0], name: 'pj-joint' }, headers: H,
  })
  const partRel = `__e2e__${name}_part.nadoc`
  await page.request.post(`${API}/design/save`, { data: { path: `workspace/${partRel}` }, headers: H })
  await page.request.post(`${API}/assembly`, { data: { name: `__e2e__${name}` }, headers: H })
  const addBody = await (await page.request.post(`${API}/assembly/instances`, {
    data: { source: { type: 'file', path: partRel }, name: 'Joint Part' }, headers: H,
  })).json()
  const insts = addBody?.assembly?.instances_v2 ?? addBody?.assembly?.instances
  const instanceId = insts[insts.length - 1].id
  // Flexible + part-joints enabled is the precondition the drag branch checks.
  await page.request.patch(`${API}/assembly/instances/${instanceId}`, {
    data: { allow_part_joints: true, mode: 'flexible' }, headers: H,
  })
  await _enterAssemblyAndFrame(page)
  return { instanceId, clusterId }
}

/**
 * Drive the part-joint ring drag and return the pending part-joint rotations it
 * records. Arms the selected cluster (the gesture's selection prerequisite),
 * then does a REAL pointer-down on the part body → drag → up so the angle
 * accumulates through _updatePartJointDrag and commits in _onAssemblyDragUp.
 * Retries a few drag vectors until a non-zero rotation is recorded.
 */
export async function dragPartJointRing(page, { instanceId, clusterId }) {
  const drags = [[70, 60], [-70, 60], [80, -50], [50, 90]]
  for (const [dx, dy] of drags) {
    await frameAssembly(page)
    await page.evaluate(([i, c]) => window.__nadocTest.selectAssemblyClusterForTest(i, c), [instanceId, clusterId])
    const cands = await assemblyInstanceCandidates(page)
    const target = cands.find(c => c.id === instanceId) ?? cands[0]
    if (!target) continue
    const px = await _pixelForInstance(page, target.x, target.y, instanceId)
    if (!px) continue
    // Real drag: down on the part → move (rotate around the +Y ring) → up.
    await page.mouse.move(px.x, px.y)
    await page.mouse.down()
    await page.mouse.move(px.x + dx / 2, px.y + dy / 2, { steps: 4 })
    await page.mouse.move(px.x + dx, px.y + dy, { steps: 4 })
    await page.mouse.up()
    await page.waitForTimeout(250)
    const pending = await page.evaluate(() => window.__nadocTest.getAssemblyPendingPartJoints())
    if (pending.some(p => Math.abs(p.jointValue ?? 0) > 1e-6)) return pending
  }
  return page.evaluate(() => window.__nadocTest.getAssemblyPendingPartJoints())
}

// ── Move/Rotate tool gesture (primary instance transform) ──────────────────
// The cluster-joint ring drag above rotates a part ABOUT a joint. The
// Move/Rotate tool instead translates/rotates the whole selected instance and
// records a PRIMARY transform in `_assemblyPendingTransforms`. Per the #36/#37
// ledger lesson, the gizmo's TransformControls handles are too small to drag at
// integer-pixel precision — so we drive the non-flaky DOM path instead: the
// Move/Rotate right-sidebar panel's numeric inputs fire a `change` →
// `_mrCommitInputs` → `_queueAssemblyPrimaryCommit`, the same map the gizmo
// onCommit feeds. This is the template the Move/Rotate panel extraction extends.

/**
 * Activate the Move/Rotate tool on the active instance (real entry point) and
 * wait for the panel to appear. Requires an instance already selected (call
 * selectAssemblyInstance first). Returns the translateRotateActive flag.
 */
export async function activateAssemblyMoveTool(page) {
  const active = await page.evaluate(() => window.__nadocTest.activateAssemblyMoveTool())
  await page.locator('#move-rotate-panel').waitFor({ state: 'visible', timeout: 4000 }).catch(() => {})
  return active
}

/**
 * Set a translation on the selected instance via the Move/Rotate panel's numeric
 * inputs (the real, non-flaky DOM commit path) and return the pending primary
 * transforms it recorded. Fills the X/Y/Z nm fields, fires `change` on the last
 * one (the listener reads all three), and reads back `_assemblyPendingTransforms`.
 */
export async function moveActiveInstanceViaPanel(page, { tx = 0, ty = 0, tz = 0 } = {}) {
  await page.locator('#mr-tx').fill(String(tx))
  await page.locator('#mr-ty').fill(String(ty))
  await page.locator('#mr-tz').fill(String(tz))
  await page.locator('#mr-tz').dispatchEvent('change')
  await page.waitForTimeout(150)
  return page.evaluate(() => window.__nadocTest.getAssemblyPendingTransforms())
}
