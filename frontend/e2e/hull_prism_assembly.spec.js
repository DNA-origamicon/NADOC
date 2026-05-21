/**
 * Verification: Hull Prism representation on the SHARED assembly renderer.
 *
 * Loads a small NADOC-built assembly, switches representation to hull-prism,
 * and asserts the shared path builds + draws a `sharedLodHull` InstancedMesh
 * (one merged extrusion-box solid per hull-prism instance) instead of demoting
 * to a far billboard.
 *
 * Run: cd frontend && npx playwright test e2e/hull_prism_assembly.spec.js --reporter=list
 * Override fixture via NADOC_HULL_FIXTURE=/path/to.nass
 */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIXTURE = process.env.NADOC_HULL_FIXTURE
  ?? resolvePath(process.cwd(), '..', 'workspace', '1 hinge test.nass')

test.setTimeout(120_000)
test.skip(!existsSync(FIXTURE), `fixture missing: ${FIXTURE}`)

async function sceneHullMeshes(page) {
  return await page.evaluate(() => {
    const dbg = window.__NADOC_DBG__
    const out = { hullMeshes: [], allInstanced: [], lod: null, srcFeatureLog: null }
    dbg.scene.traverse((o) => {
      if (!o.isInstancedMesh) return
      const rec = { name: o.name, count: o.count, visible: o.visible, mat: o.material?.type }
      out.allInstanced.push(rec)
      if (o.name === 'sharedLodHull') out.hullMeshes.push(rec)
    })
    const ar = dbg.assemblyRenderer
    out.lod = ar?.probeLod ? ar.probeLod() : null
    // Peek at the first source's design.feature_log length (does the part have
    // build history → extrusion-box path, vs the scan fallback?).
    try {
      const sm = ar?._debugSources?.() ?? null
      out.srcFeatureLog = sm
    } catch { /* no debug accessor — fine */ }
    return out
  })
}

test('hull-prism renders as instanced grey boxes in an assembly (shared path)', async ({ page }) => {
  page.on('console', msg => {
    const t = msg.text()
    if (t.startsWith('[API') && t.includes('/assembly/instances/')) return
    if (t.startsWith('[shared_renderer]') || t.startsWith('[diag]') || msg.type() === 'error')
      console.log(`[browser ${msg.type()}] ${t}`)
  })
  page.on('pageerror', err => console.log(`[browser error] ${err.message}`))

  await page.addInitScript(() => localStorage.setItem('NADOC_SHARED_RENDERER', 'true'))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__, null, { timeout: 15_000 })

  const nass = readFileSync(FIXTURE, 'utf-8')
  await page.evaluate(async (content) => {
    const api = await import('/src/api/client.js')
    const ok = await api.importAssembly(content)
    if (!ok) throw new Error('importAssembly returned falsy')
    const assembly = window.__NADOC_DBG__.store.getState().currentAssembly
    await window.__NADOC_DBG__.assemblyRenderer.rebuild(assembly)
  }, nass)
  await page.waitForFunction(
    () => (window.__NADOC_DBG__?.store?.getState?.()?.currentAssembly?.instances?.length ?? 0) > 0,
    null, { timeout: 30_000 },
  )

  await page.evaluate(() => {
    document.getElementById('welcome-screen')?.style.setProperty('display', 'none')
    document.getElementById('welcome')?.style.setProperty('display', 'none')
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  })
  await page.waitForTimeout(1500)

  const before = await sceneHullMeshes(page)
  console.log('\n=== before hull-prism ===\n', JSON.stringify(before, null, 2))

  // Switch representation to Hull Prism via the menu button.
  const clicked = await page.evaluate(() => {
    const btn = document.getElementById('menu-view-hull-prism')
    if (!btn) return false
    btn.click()
    return true
  })
  expect(clicked, 'menu-view-hull-prism button exists').toBe(true)

  await page.waitForFunction(
    () => {
      const inst = window.__NADOC_DBG__?.store?.getState?.()?.currentAssembly?.instances ?? []
      return inst.length > 0 && inst.every(i => i.representation === 'hull-prism')
    },
    null, { timeout: 60_000 },
  )
  // The rep change triggers a full async renderer rebuild (re-fetch geometry +
  // rebuild sources, ~seconds per source) — and this fixture can fire several
  // overlapping rebuilds.  Poll the live scene with expect.poll so the
  // assertion retries until a hull is actually drawing (race-free vs a probe
  // that lands mid-rebuild when _sources is transiently empty).
  await expect.poll(async () => {
    return await page.evaluate(() => {
      let count = 0, visible = false
      window.__NADOC_DBG__?.scene?.traverse(o => {
        if (o.isInstancedMesh && o.name === 'sharedLodHull') { count = o.count; visible = o.visible }
      })
      return (visible && count > 0) ? count : 0
    })
  }, { timeout: 60_000, message: 'sharedLodHull draws ≥1 instance' }).toBeGreaterThan(0)

  const after = await sceneHullMeshes(page)
  console.log('\n=== after hull-prism ===\n', JSON.stringify(after, null, 2))
  await page.screenshot({ path: 'e2e/screenshots/hull_prism_assembly.png' })

  // The far billboard must NOT be drawing the same instances as the hull.
  const far = after.allInstanced.find(m => m.name === 'sharedLodFar')
  if (far) expect(far.count, 'far billboard not drawing the hull instances').toBe(0)
})
