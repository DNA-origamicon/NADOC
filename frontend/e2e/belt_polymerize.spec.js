/**
 * Polymerize along a belt: a seed belt rider repeated around the loop becomes N
 * belt riders (clones of the seed instance) at evenly-spaced arc_params, sharing
 * the seed's local_transform so they ride together.
 *
 * Drives the geometry helpers exposed on __NADOC_DBG__ (beltFillCount /
 * polymerizeBelt) against workspace/belt_test.nass.
 * Run: cd frontend && npx playwright test e2e/belt_polymerize.spec.js \
 *        --config playwright.bench.config.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIXTURE = resolvePath(process.cwd(), '..', 'workspace', 'belt_test.nass')
const I4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
test.setTimeout(120_000)
test.skip(!existsSync(FIXTURE), `fixture missing: ${FIXTURE}`)

test('polymerize a belt rider around the loop', async ({ page }) => {
  page.on('pageerror', e => console.log('[pageerror] ' + e.message))
  await page.goto('http://localhost:5173/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.store, null, { timeout: 30_000 })

  const nass = readFileSync(FIXTURE, 'utf-8')
  await page.evaluate(async (content) => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(content)
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  }, nass)
  await page.waitForFunction(
    () => (window.__NADOC_DBG__.store.getState().currentAssembly?.joints?.length ?? 0) === 2,
    null, { timeout: 30_000 })
  await page.waitForTimeout(2500)

  // Create a belt + a seed rider via the API.
  const seed = await page.evaluate(async (I4) => {
    const api = await import('/src/api/client.js')
    const a = window.__NADOC_DBG__.store.getState().currentAssembly
    const rev = a.joints.filter(j => j.joint_type === 'revolute')
    await api.createBeltPath({
      name: 'B',
      pulley_a: { joint_id: rev[0].id, side: 'b', radius: 3, center_world: [0, 0, 0], connector_world: [3, 0, 0] },
      pulley_b: { joint_id: rev[1].id, side: 'b', radius: 2, center_world: [12, 0, 0], connector_world: [14, 0, 0] },
    })
    const beltId = window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths[0].id
    await api.createBeltRider({
      belt_path_id: beltId, instance_id: rev[1].instance_b_id, connector_label: 'PulleyB_rim',
      arc_param: 0.1, ref_angle: 0, local_transform: I4, transform: { values: I4 },
    })
    const a2 = window.__NADOC_DBG__.store.getState().currentAssembly
    return { riderId: a2.belt_riders[0].id, instCount: a2.instances.length }
  }, I4)
  console.log('seed:', JSON.stringify(seed))

  // Auto fill count.
  const fill = await page.evaluate((rid) => window.__NADOC_DBG__.beltFillCount(rid), seed.riderId)
  console.log('fill:', JSON.stringify(fill))
  expect(fill).not.toBe(null)
  expect(fill.count).toBeGreaterThanOrEqual(2)

  // Polymerize to a chain of 3 (2 new copies).
  const result = await page.evaluate(async (rid) => {
    await window.__NADOC_DBG__.polymerizeBelt(rid, 3)
    const a = window.__NADOC_DBG__.store.getState().currentAssembly
    return {
      riders: a.belt_riders.length,
      instances: a.instances.length,
      arcs: a.belt_riders.map(r => +(r.arc_param ?? 0).toFixed(3)).sort(),
      refAngles: [...new Set(a.belt_riders.map(r => r.ref_angle))],
    }
  }, seed.riderId)
  console.log('after polymerize:', JSON.stringify(result))

  // 1 seed + 2 new riders; 2 new instances; all share ref_angle; distinct arcs.
  expect(result.riders).toBe(3)
  expect(result.instances).toBe(seed.instCount + 2)
  expect(new Set(result.arcs).size).toBe(3)
  expect(result.refAngles).toEqual([0])
})
