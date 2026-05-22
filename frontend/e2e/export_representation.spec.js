/**
 * Final render representation for photo mode (path-to-thousands):
 *  - the photo preview keeps the working representation,
 *  - the per-assembly export_representation persists (round-trips through .nass),
 *  - a PNG export temporarily upgrades all instances to the export rep, then
 *    restores the working reps.
 *
 * Run: cd frontend && npx playwright test e2e/export_representation.spec.js \
 *        --config playwright.bench.config.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIX = resolvePath(process.cwd(), '..', 'workspace', 'bench_fixtures', 'bench_hinge_001.nass')
test.skip(!existsSync(FIX), `fixture missing: ${FIX}`)

test('export representation: preview stays working, export upgrades + restores, persists', async ({ page }) => {
  test.setTimeout(180_000)
  page.on('pageerror', e => console.log('[pageerror] ' + e.message))
  await page.addInitScript(() => localStorage.setItem('NADOC_SHARED_RENDERER', 'true'))
  await page.goto('http://localhost:5173/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.assemblyRenderer, null, { timeout: 30_000 })

  // Load the 1-instance assembly (saved as cylinders) and enter assembly mode.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const res = await api.getLibraryFileContent('bench_fixtures/bench_hinge_001.nass')
    await api.importAssembly(res.content)
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  })
  await page.waitForFunction(() => (window.__NADOC_DBG__.store.getState().currentAssembly?.instances?.length ?? 0) === 1, null, { timeout: 30_000 })
  // Force cylinders as the working rep (mirrors normal assembly default).
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const insts = window.__NADOC_DBG__.store.getState().currentAssembly.instances
    await api.batchPatchInstances(insts.map(i => ({ id: i.id, representation: 'cylinders' })))
  })
  await page.waitForTimeout(3000)

  // Enter photo mode via the tab button.
  await page.evaluate(() => document.getElementById('photo-tab-btn')?.click())
  await page.waitForFunction(() => window.__NADOC_DBG__.store.getState().photoActive === true, null, { timeout: 20_000 })
  await page.waitForTimeout(1500)

  // ── A. Preview keeps the working (cylinders) rep; default export rep = 'full' ──
  const a = await page.evaluate(() => {
    const D = window.__NADOC_DBG__
    const visChain = o => { let p = o; while (p) { if (!p.visible) return false; p = p.parent } return true }
    let beads = 0, mid = 0
    D.scene.traverse(o => {
      if (!(o.isMesh || o.isInstancedMesh) || !o.name || !visChain(o) || (o.count ?? 1) === 0) return
      if (o.name === 'backboneSpheres') beads++
      if (o.name === 'sharedLodMid') mid++
    })
    return {
      beadsDrawn: beads, midDrawn: mid,
      exportRep: D.store.getState().currentAssembly.export_representation,
      dropdown: document.getElementById('photo-export-rep')?.value,
    }
  })
  console.log('A (preview):', JSON.stringify(a))
  expect(a.beadsDrawn, 'preview not at full (no bp beads)').toBe(0)
  expect(a.exportRep, 'export rep defaults to full').toBe('full')
  expect(a.dropdown, 'dropdown reflects the assembly setting').toBe('full')

  // ── B. Persistence: change via the dropdown → store + .nass round-trip ──
  await page.evaluate(() => {
    const sel = document.getElementById('photo-export-rep')
    sel.value = 'cylinders'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.waitForFunction(
    () => window.__NADOC_DBG__.store.getState().currentAssembly.export_representation === 'cylinders',
    null, { timeout: 10_000 },
  )
  const nassRep = await page.evaluate(async () => {
    const r = await fetch('/api/assembly/export')
    const txt = await r.text()
    return JSON.parse(txt).export_representation
  })
  console.log('B (.nass export_representation):', nassRep)
  expect(nassRep, 'export rep round-trips through .nass').toBe('cylinders')
  // set back to full for the export test
  await page.evaluate(() => {
    const sel = document.getElementById('photo-export-rep')
    sel.value = 'full'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.waitForFunction(() => window.__NADOC_DBG__.store.getState().currentAssembly.export_representation === 'full', null, { timeout: 10_000 })

  // ── C. PNG export upgrades to full mid-render, restores cylinders after ──
  await page.evaluate(() => {
    const D = window.__NADOC_DBG__
    window.__rebuildReps = []
    D.assemblyRenderer.onRebuildComplete(() => {
      window.__rebuildReps.push(D.store.getState().currentAssembly.instances.map(i => i.representation))
    })
    window.__blobs = 0
    const orig = URL.createObjectURL
    URL.createObjectURL = (b) => { window.__blobs++; return orig.call(URL, b) }
    // small render
    const res = document.getElementById('photo-res-preset'); if (res) { res.value = 'screen'; res.dispatchEvent(new Event('change', { bubbles: true })) }
    document.getElementById('photo-export-btn')?.click()
  })
  // Wait for the export to finish: button re-enabled AND working reps restored.
  await page.waitForFunction(() => {
    const btn = document.getElementById('photo-export-btn')
    const reps = window.__NADOC_DBG__.store.getState().currentAssembly.instances.map(i => i.representation)
    return btn && !btn.disabled && reps.every(r => r === 'cylinders')
  }, null, { timeout: 150_000 })

  const c = await page.evaluate(() => ({
    sawFull: (window.__rebuildReps ?? []).some(r => r.length && r.every(x => x === 'full')),
    finalReps: window.__NADOC_DBG__.store.getState().currentAssembly.instances.map(i => i.representation),
    blobs: window.__blobs,
  }))
  console.log('C (export):', JSON.stringify(c))
  expect(c.sawFull, 'instances were upgraded to full during export').toBe(true)
  expect(c.finalReps.every(r => r === 'cylinders'), 'working reps restored after export').toBe(true)
  expect(c.blobs, 'a PNG blob was produced').toBeGreaterThan(0)
})
