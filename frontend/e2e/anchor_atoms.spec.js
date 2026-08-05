/**
 * Per-anchor atom holds: the NAMD Anchors table + the per-ATOM purple halo.
 *
 * Three things this proves that no unit test can:
 *   1. Each anchor row owns its Hold-atoms choice, and "Apply hold to all" goes BLANK
 *      when the rows disagree.
 *   2. With an atomistic representation on, the halo lands on the atoms the anchor
 *      actually holds — one sphere per phosphorus for "P only", ~20 for all-heavy —
 *      and every glowing sphere sits ON a real atom of the right name.
 *   3. Leaving the atomistic rep drops back to the coarse per-nucleotide halo.
 *
 * Runs against the config's throwaway backend (:8002), never the user's dev server.
 * Loader mirrors anchor_glow_no_field.spec.js (scene_harness.loadScaffoldedPart is
 * broken on master).
 */
import { test, expect } from '@playwright/test'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002') + '/api'

async function loadPopulatedHelix(page, { doc, name, lengthBp = 32 }) {
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', `__e2e__${name}`)   // teardown removes __e2e__ files
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await expect
    .poll(async () => (await page.request.get(`${API}/design`, { headers: H })).status(),
      { timeout: 15_000, message: `backend never got a design for doc ${doc}` })
    .toBe(200)

  const res = await page.request.post(`${API}/design/helix-at-cell`, {
    data: { row: 0, col: 0, length_bp: lengthBp, populate_strands: true }, headers: H,
  })
  expect(res.status(), `helix-at-cell failed: ${await res.text()}`).toBe(201)

  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-anchor-atoms', docId: d })
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
}

/** Open the Simulations tab on the NAMD engine with the Anchors card expanded. */
async function openNamdAnchors(page) {
  await page.getByRole('button', { name: 'Simulations', exact: true }).first().click()
  await page.waitForTimeout(300)
  await page.locator('.engine-selector-btn').filter({ hasText: /NAMD/i }).first().click()
  await page.waitForTimeout(300)
  await page.click('#md-anchors-toggle')
  await expect(page.locator('#md-anchors-body')).toBeVisible()
}

async function lassoStrands(page, n) {
  return page.evaluate((count) => {
    const st = window.__nadocTest.store.getState()
    const ids = [...new Set((st.currentDesign?.strands || []).map(s => s.id))].slice(0, count)
    window.__nadocTest.store.setState({ multiSelectedStrandIds: ids, selectedObject: null })
    return ids.length
  }, n)
}

const rowKeys = (page) => page.evaluate(() =>
  [...document.querySelectorAll('#md-anchors-list [data-key]')].map(e => e.dataset.key))
const glowCount = (page) => page.evaluate(() => window.__nadocTest.anchors.glowCount())

/** Record the NAMD card's live anchor set off its own halo event — the same channel
 *  main.js listens on, so this observes the real descriptors rather than a test hook. */
async function watchNamdAnchors(page) {
  await page.evaluate(() => {
    window.__e2eNamdAnchors = []
    window.addEventListener('nadoc:anchors-change', (e) => {
      if (e.detail?.engine === 'namd') window.__e2eNamdAnchors = e.detail.anchors
    })
  })
}

/** Set one row's Hold-atoms select and fire the real change event. */
async function setRowAtoms(page, key, value) {
  await page.selectOption(`#md-anchors-list [data-key="${key}"] select`, value)
  await page.waitForTimeout(250)
}

/** Turn on an atomistic representation and wait for the atoms to actually load. */
async function enableAtomistic(page, key = 'F7') {
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press(key)
  // The mode flips synchronously but the atoms arrive over the wire, so wait for the
  // actual instanced meshes — this is exactly why the halo subscribes to the renderer's
  // own atom-set signal rather than to nadoc:representation-change.
  await page.waitForFunction(() => {
    const ar = window.__nadocTest?.getAtomisticRenderer?.()
    if (!ar || ar.getMode() === 'off') return false
    let atoms = 0
    window.__nadocTest.scene.traverse(o => {
      if (o.isInstancedMesh && o.name === 'atomSpheres') atoms += o.count
    })
    return atoms > 0
  }, null, { timeout: 60_000 })
  await page.waitForTimeout(600)
}

test.describe('Per-anchor atom holds', () => {
  test('each row owns its Hold-atoms choice; Apply-to-all blanks when they disagree', async ({ page }) => {
    await loadPopulatedHelix(page, { doc: 'e2e-anchor-atoms-ui', name: 'anchor-atoms-ui' })
    await openNamdAnchors(page)
    await watchNamdAnchors(page)

    // BASE anchors, both strands of ONE base pair — the case every real NAMD job on this
    // design uses, and the case whose two rows used to render identically.
    const picked = await page.evaluate(() => {
      const h = window.__nadocTest.store.getState().currentDesign.helices[0]
      const keys = [`${h.id}:7:FORWARD`, `${h.id}:7:REVERSE`]
      window.__nadocTest.store.setState({ multiSelectedBaseKeys: keys, selectedObject: null })
      return keys.length
    })
    expect(picked).toBe(2)
    await page.click('#md-anchors-add')
    await page.waitForTimeout(300)

    const keys = await rowKeys(page)
    expect(keys, 'two anchor rows').toHaveLength(2)

    // The column has to be USABLE, not merely present. A `width:100%` label cell once
    // starved this select to 6px in the ~230px sidebar, which reads as "no column".
    const geom = await page.evaluate(() => {
      const list = document.getElementById('md-anchors-list')
      const sel = list.querySelector('[data-key] select')
      const r = sel.getBoundingClientRect(), lr = list.getBoundingClientRect()
      return { selW: Math.round(r.width), fitsInBox: r.right <= lr.right + 1,
               noHScroll: list.scrollWidth <= list.clientWidth + 1,
               labels: [...list.querySelectorAll('[data-key] td:first-child')].map(t => t.textContent) }
    })
    expect(geom.selW, 'the Hold-atoms select is actually wide enough to use')
      .toBeGreaterThan(60)
    expect(geom.fitsInBox, 'and sits inside the visible box').toBe(true)
    expect(geom.noHScroll, 'nothing is pushed off to the right').toBe(true)
    // Compact labels: helix NUMBER + bp + strand role, never a lattice id or a UUID.
    for (const t of geom.labels) {
      expect(t, `label "${t}" is helix number + bp + strand role`).toMatch(/^H\d+:bp\d+ (Scaf|Stap)$/)
      expect(t.length).toBeLessThanOrEqual(14)
    }
    // The two strands of one base pair must NOT read the same, and one is the scaffold.
    expect(new Set(geom.labels).size, 'the pair gets two distinct rows').toBe(2)
    expect(geom.labels.some(t => t.endsWith('Scaf')), 'one side is the scaffold').toBe(true)
    expect(geom.labels.some(t => t.endsWith('Stap')), 'the other is a staple').toBe(true)

    // Every row carries a Hold-atoms select cloned from the ONE preset list.
    const optionsPerRow = await page.evaluate(() =>
      [...document.querySelectorAll('#md-anchors-list [data-key] select')]
        .map(s => [...s.options].map(o => o.value)))
    expect(optionsPerRow).toHaveLength(2)
    for (const opts of optionsPerRow) expect(opts).toEqual(['', "C1'", 'P', "P,C1'"])

    // Rows start uniform, so the group select shows their shared value.
    expect(await page.locator('#md-anchors-atoms').inputValue()).toBe('')

    // Disagree → the group select goes blank rather than claiming a value.
    await setRowAtoms(page, keys[0], 'P')
    expect(await page.evaluate(() => document.getElementById('md-anchors-atoms').selectedIndex),
      'mixed rows blank the group select').toBe(-1)
    expect(await page.locator(`#md-anchors-list [data-key="${keys[1]}"] select`).inputValue(),
      'the other row is untouched').toBe('')

    // Agree again → it un-blanks.
    await setRowAtoms(page, keys[1], 'P')
    expect(await page.locator('#md-anchors-atoms').inputValue()).toBe('P')

    // Apply-to-all writes every row.
    await page.selectOption('#md-anchors-atoms', "C1'")
    await page.waitForTimeout(250)
    for (const k of await rowKeys(page)) {
      expect(await page.locator(`#md-anchors-list [data-key="${k}"] select`).inputValue()).toBe("C1'")
    }
  })

  test('the halo lands on the exact atoms held, and reverts when atomistic is off', async ({ page }) => {
    await loadPopulatedHelix(page, { doc: 'e2e-anchor-atoms-glow', name: 'anchor-atoms-glow' })
    await openNamdAnchors(page)
    await watchNamdAnchors(page)

    // ONE strand anchor keeps the numbers small enough to reason about exactly.
    expect(await lassoStrands(page, 1)).toBe(1)
    await page.click('#md-anchors-add')
    await page.waitForTimeout(300)
    const [key] = await rowKeys(page)
    expect(key).toBeTruthy()

    const cgSpheres = await glowCount(page)
    expect(cgSpheres, 'coarse halo: one sphere per anchored nucleotide').toBeGreaterThan(0)

    await enableAtomistic(page, 'F7')

    // "P only" → exactly one sphere per anchored nucleotide THAT HAS a phosphorus.
    // 5′ termini have none, so this is ≤ the nucleotide count, never more.
    await setRowAtoms(page, key, 'P')
    const pOnly = await glowCount(page)
    expect(pOnly, 'P-only halo is at most one per nucleotide').toBeLessThanOrEqual(cgSpheres)
    expect(pOnly, 'and it is drawn').toBeGreaterThan(0)

    // THE measurement: every glowing sphere must sit ON a phosphorus of an anchored
    // nucleotide. Positions are compared against the real atom coordinates, so this is
    // "the glow shows the exact atoms chosen" measured rather than eyeballed.
    const pCheck = await page.evaluate(async () => {
      const { buildAnchorAtomIndex } = await import('/src/scene/anchor_glow.js')
      const design = window.__nadocTest.store.getState().currentDesign
      const ar = window.__nadocTest.getAtomisticRenderer()
      const anchors = window.__e2eNamdAnchors || []
      const idx = buildAnchorAtomIndex(anchors, design)
      const entries = ar.anchorAtomEntries(idx, { scale: 1.4 }) || []

      // Independently collect where the P atoms of anchored nucleotides actually are.
      const want = new Set()
      const centroid = ar.centroidOf(a => {
        const k = `${a.helix_id}:${a.bp_index}:${String(a.direction).toUpperCase()}`
        if (!idx.has(k) || a.name !== 'P') return false
        want.add(`${a.x.toFixed(3)},${a.y.toFixed(3)},${a.z.toFixed(3)}`)
        return true
      })
      const hit = entries.filter(e =>
        want.has(`${e.pos.x.toFixed(3)},${e.pos.y.toFixed(3)},${e.pos.z.toFixed(3)}`)).length
      return { keys: idx.size, atoms: anchors.length, n: entries.length,
               wantedP: want.size, onAP: hit, centroid: !!centroid }
    })
    expect(pCheck.atoms, 'the card really has an anchor').toBeGreaterThan(0)
    expect(pCheck.keys, 'the index covers the anchored nucleotides').toBeGreaterThan(0)
    expect(pCheck.n, 'and resolves to the sphere count the layer drew').toBe(pOnly)
    expect(pCheck.wantedP, 'anchored nucleotides do have phosphorus atoms').toBeGreaterThan(0)
    expect(pCheck.onAP, 'EVERY glowing sphere sits on a P of an anchored base')
      .toBe(pCheck.n)

    // P + C1′ → strictly more spheres than P alone (every nucleotide has a C1′).
    await setRowAtoms(page, key, "P,C1'")
    const both = await glowCount(page)
    expect(both, 'two atoms per base beats one').toBeGreaterThan(pOnly)

    // All heavy atoms → many more again (~20 per base).
    await setRowAtoms(page, key, '')
    const allHeavy = await glowCount(page)
    expect(allHeavy, 'all-heavy is the largest').toBeGreaterThan(both)
    expect(allHeavy / cgSpheres, 'roughly the heavy-atom count of a nucleotide')
      .toBeGreaterThan(5)

    // Back to a coarse representation → the per-nucleotide halo returns.
    await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
    await page.keyboard.press('F4')
    await page.waitForTimeout(800)
    expect(await glowCount(page), 'coarse halo restored, one sphere per nucleotide')
      .toBe(cgSpheres)
  })
})
