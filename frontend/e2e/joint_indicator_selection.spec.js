/**
 * Joint/connector indicators are selection-gated (path-to-thousands scale fix).
 *
 * The orange mate/joint indicators + connector dots are non-instanced meshes
 * (~15 per part) that, drawn for every part, dominate the frame at scale. They
 * should now draw ONLY for the selected instance (none when nothing selected).
 *
 * Run: cd frontend && npx playwright test e2e/joint_indicator_selection.spec.js \
 *        --config playwright.bench.config.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIXTURE = resolvePath(process.cwd(), '..', 'workspace', 'bench_fixtures', 'bench_hinge_020.nass')
test.setTimeout(120_000)
test.skip(!existsSync(FIXTURE), `fixture missing: ${FIXTURE}`)

// Count visible non-instanced draw meshes + visible 'assemblyMateIndicator' groups.
async function counts(page) {
  return await page.evaluate(() => {
    const D = window.__NADOC_DBG__
    const visChain = o => { let p = o; while (p) { if (!p.visible) return false; p = p.parent } return true }
    let nonInstVisible = 0, mateGroupsVisible = 0
    D.scene.traverse(o => {
      if ((o.isMesh || o.isLine || o.isLineSegments) && !o.isInstancedMesh && o.material && visChain(o)) nonInstVisible++
      if (o.name === 'assemblyMateIndicator' && visChain(o)) mateGroupsVisible++
    })
    return { nonInstVisible, mateGroupsVisible }
  })
}

test('joint + connector indicators draw only for the selected instance', async ({ page }) => {
  page.on('pageerror', e => console.log('[pageerror] ' + e.message))
  await page.addInitScript(() => localStorage.setItem('NADOC_SHARED_RENDERER', 'true'))
  await page.goto('http://localhost:5173/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.assemblyRenderer, null, { timeout: 30_000 })

  const nass = readFileSync(FIXTURE, 'utf-8')
  await page.evaluate(async (content) => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(content)
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  }, nass)
  await page.waitForFunction(() => (window.__NADOC_DBG__.store.getState().currentAssembly?.instances?.length ?? 0) === 20, null, { timeout: 30_000 })
  await page.waitForTimeout(5000)  // settle rebuild + async connector pass

  // ── Nothing selected → indicators hidden ────────────────────────────────
  const before = await counts(page)
  console.log('before (no selection):', JSON.stringify(before))
  expect(before.mateGroupsVisible, 'no joint indicators visible when nothing selected').toBe(0)
  expect(before.nonInstVisible, 'almost no non-instanced meshes drawn when nothing selected').toBeLessThan(50)

  // ── Select an instance that has a joint ─────────────────────────────────
  const sel = await page.evaluate(() => {
    const D = window.__NADOC_DBG__
    const asm = D.store.getState().currentAssembly
    const j = asm.joints.find(j => j.instance_a_id && j.instance_b_id)
    const id = j.instance_a_id
    const touching = asm.joints.filter(x => x.instance_a_id === id || x.instance_b_id === id).length
    D.store.setState({ activeInstanceId: id })
    return { id, touching }
  })
  await page.waitForTimeout(800)

  const after = await counts(page)
  console.log('after (selected ' + sel.id.slice(0, 6) + ', touches ' + sel.touching + ' joints):', JSON.stringify(after))
  // Its joints now show (one 'assemblyMateIndicator' group per touching joint).
  expect(after.mateGroupsVisible, 'selected instance shows its joint indicators').toBe(sel.touching)
  // Still tiny vs the ~3000 that drew for all parts before the fix.
  expect(after.nonInstVisible, 'only the selected part\'s indicators draw').toBeLessThan(80)

  // ── Deselect → back to none ──────────────────────────────────────────────
  await page.evaluate(() => window.__NADOC_DBG__.store.setState({ activeInstanceId: null }))
  await page.waitForTimeout(500)
  const cleared = await counts(page)
  console.log('after deselect:', JSON.stringify(cleared))
  expect(cleared.mateGroupsVisible, 'deselect hides indicators again').toBe(0)
})
