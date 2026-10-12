import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../..')
const fixture = JSON.parse(execFileSync(path.join(root, '.venv/bin/python'), ['-c', `
import json,numpy as np
from scipy.spatial.transform import Rotation
from tests.test_cluster_join_api import make_join_design
from tests.test_cluster_join_core import request
from backend.core.cluster_join import propose_cluster_join
d=make_join_design(2,n_helices=8,routed=False)
_,r=propose_cluster_join(d,request(d,kinds=('side','end'),gap=2))
m=np.array(r['donor_world_delta']).reshape(4,4,order='F')
print(json.dumps(dict(design=d.model_dump(mode='json'),pose=dict(world_translation=m[:3,3].tolist(),world_rotation=Rotation.from_matrix(m[:3,:3]).as_quat().tolist()))))
`], { cwd: root, maxBuffer: 8*1024*1024 }).toString())
const state = page => page.evaluate(() => window.__nadocTest.clusterJoin.getState())
const design = page => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)

// Keep actual WebGL and mouse interactions; reduce software-raster cost in CI.
test.use({ deviceScaleFactor: 0.5, trace: 'off', viewport: { width: 1920, height: 1100 }, launchOptions: { args: ['--enable-webgl', '--ignore-gpu-blocklist'] } })
test('unrouted Join creates every previewed scaffold connection with atomic undo and redo', async ({ page }) => {
  test.setTimeout(300_000)
  page.setDefaultTimeout(20000)
  const errors = [], applied = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route(/\/api\/(oxdna|md|mrdna|lammps|cando|snupi|blade)\/jobs(?:\?.*)?$/, route => route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.continue())
  await page.addInitScript(() => localStorage.setItem('nadoc.hint.selModifiers.v1', '1'))
  await page.goto('/?doc=e2e-free-join')
  await page.waitForFunction(() => !!window.__nadocTest?.clusterJoin)
  await page.getByRole('button', { name: 'File', exact: true }).hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__free-join')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async content => {
    await (await import('/src/api/client.js')).importDesign(JSON.stringify(content))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    window.__nadocTest.applyCameraPoseForTest({ position: [85, 65, 90], target: [10, 5, 18], up: [0, 0, 1] })
  }, fixture.design)
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-join').click()
  await expect.poll(async () => (await state(page)).loading).toBe(false)
  const panel = page.locator('#cluster-join-panel')
  await panel.getByRole('button', { name: 'Free movement', exact: true }).click()
  // Click the actual branch body using the projected middle of a helix.
  const points = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const t = window.__nadocTest
    const c = store.getState().currentDesign.cluster_transforms.find(c => c.id === 'join_cluster_1')
    return c.helix_ids.map(id => {
      const a = store.getState().currentHelixAxes[id]
      return t.clusterJoin.projectWorld(a.start.map((v,i) => (v+a.end[i])/2))
    })
  })
  for (const p of points) {
    await page.mouse.click(p.x, p.y)
    if ((await state(page)).second?.cluster_id === 'join_cluster_1') break
  }
  expect((await state(page)).second?.cluster_id).toBe('join_cluster_1')
  const before = await design(page)
  await panel.getByLabel('Connection reach', { exact: true }).fill('6')
  // Establish a reproducible nearby pose, then exercise an actual gizmo drag.
  await page.evaluate(pose => window.__nadocTest.clusterJoin.setFreePose(pose), fixture.pose)
  await expect.poll(async () => (await state(page)).preview?.connection_count ?? 0, { timeout: 30000 }).toBeGreaterThan(1)
  const ready = await state(page)
  expect(ready.preview.deferred_routing).toBe(false)
  expect(ready.preview.connection_count).toBeGreaterThanOrEqual(4)
  expect((await design(page)).strands).toEqual(before.strands)
  await expect(panel.locator('[data-join-report]')).toContainText('nicks and ligations')
  page.on('request', r => { if (r.url().endsWith('/cluster-join/apply')) applied.push(r.postDataJSON()) })
  await panel.locator('[data-join-apply]').click()
  await expect(panel).toBeHidden({ timeout: 30000 })
  expect(applied).toHaveLength(1)
  expect(applied[0].world_translation).toEqual(fixture.pose.world_translation)
  const after = await design(page)
  expect(after.strands).not.toEqual(before.strands)
  expect(after.helices.length - before.helices.length).toBe(2 * ready.preview.connection_count)
  expect(after.forced_ligations.length - before.forced_ligations.length).toBe(4 * ready.preview.connection_count)
  expect(after.cluster_join_constraints).toHaveLength(0)
  for (const bridge of ready.preview.bridges) {
    const domain = after.strands.flatMap(s => s.domains).find(d => d.helix_id === bridge.helix_id)
    expect(domain).toBeTruthy()
    expect(domain.end_bp - domain.start_bp + 1).toBe(bridge.extra_bases)
  }
  const visibleConstraints = () => page.evaluate(() => window.__nadocTest.scene.getObjectByName('cluster-join-constraints').children.length)
  expect(await visibleConstraints()).toBe(0)
  expect(after.feature_log.at(-1).op_kind).toBe('cluster-join')
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect((await design(page)).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await design(page)).strands).toEqual(before.strands)
  expect(await visibleConstraints()).toBe(0)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  expect((await design(page)).cluster_transforms).toEqual(after.cluster_transforms)
  expect((await design(page)).strands).toEqual(after.strands)
  expect((await design(page)).cluster_join_constraints).toEqual(after.cluster_join_constraints)
  expect(await visibleConstraints()).toBe(0)
  // Join-created ssDNA lives outside both rigid clusters, but its complete
  // tether set must still enable and feed the normal Move/Rotate tool.
  const tetherCheck = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { buildTetherPayload } = await import('/src/scene/flex_relax.js')
    const t = window.__nadocTest
    const info = await api.getFlexibleConnections()
    const payload = buildTetherPayload(info.connections, 'join_cluster_1',
      t.store.getState().currentDesign, t.getDesignRenderer().getBackboneEntries())
    return { gate: info.gates.join_cluster_1.gate, count: payload.connections.length,
      allResolve: payload.connections.every(c => payload.resolveWorldPos(c.movingKey)
        && payload.resolveWorldPos(c.fixedKey) && c.contour > 0) }
  })
  expect(tetherCheck.gate).toBe(true)
  expect(tetherCheck.count).toBe(2 * ready.preview.connection_count)
  expect(tetherCheck.allResolve).toBe(true)
  const move = await page.evaluate(() => window.__nadocTest.activateDesignMoveTool('join_cluster_1'))
  expect(move.pivotOptions).toContain('ssdna')
  await page.locator('#mr-pivot-sel').selectOption('ssdna')
  await expect(page.getByText('Constrained: drag the cluster — ssDNA tethers & connections won’t overstretch', { exact: true })).toBeVisible()
  await expect(page.locator('#mr-pivot-sel')).toHaveValue('ssdna')
  expect(errors).toEqual([])
})
