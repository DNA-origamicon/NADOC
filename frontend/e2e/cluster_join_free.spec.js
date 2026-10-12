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
d=make_join_design(2,n_helices=12)
_,r=propose_cluster_join(d,request(d,kinds=('side','end'),gap=2))
m=np.array(r['donor_world_delta']).reshape(4,4,order='F')
print(json.dumps(dict(design=d.model_dump(mode='json'),pose=dict(world_translation=m[:3,3].tolist(),world_rotation=Rotation.from_matrix(m[:3,:3]).as_quat().tolist()))))
`], { cwd: root, maxBuffer: 8*1024*1024 }).toString())
const state = page => page.evaluate(() => window.__nadocTest.clusterJoin.getState())
const design = page => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)

// Keep actual WebGL and mouse interactions; reduce software-raster cost in CI.
test.use({ deviceScaleFactor: 0.5, trace: 'off', viewport: { width: 1920, height: 1100 }, launchOptions: { args: ['--enable-webgl', '--ignore-gpu-blocklist'] } })
test('free Join moves a cluster with a real gizmo, previews multiple bridges, applies once and undoes', async ({ page }) => {
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
  expect((await design(page)).cluster_transforms).toEqual(before.cluster_transforms)
  await panel.getByRole('button', { name: 'Rotate', exact: true }).click()
  expect((await state(page)).movementMode).toBe('rotate')
  await panel.getByRole('button', { name: 'Translate', exact: true }).click()
  // Find a visible X gizmo handle; drag it far enough to lose the nearby contacts.
  const handle = await page.evaluate(async () => {
    const t = window.__nadocTest
    const helper = t.scene.getObjectByName('join-movement-gizmo')
    helper.updateMatrixWorld(true)
    const hits = []
    helper.traverseVisible(o => { if (o.name === 'X' && o.isMesh && o.visible && o.parent?.visible) hits.push(o) })
    return hits.map(o => {
      o.geometry.computeBoundingBox()
      return t.clusterJoin.projectWorld(o.geometry.boundingBox.getCenter(o.position.clone()).applyMatrix4(o.matrixWorld).toArray())
    })
  })
  let dragged = false
  for (const p of handle) {
    await page.mouse.move(p.x, p.y); await page.mouse.down(); await page.mouse.move(p.x+140, p.y+35, { steps: 12 }); await page.mouse.up()
    if (JSON.stringify((await state(page)).freePose) !== JSON.stringify(ready.freePose)) { dragged = true; break }
  }
  expect(dragged).toBe(true)
  const moved = await state(page)
  expect(moved.freePose.world_translation[0]).not.toBeCloseTo(ready.freePose.world_translation[0])
  expect(moved.freePose.world_translation[1]).toBeCloseTo(ready.freePose.world_translation[1])
  expect(moved.freePose.world_translation[2]).toBeCloseTo(ready.freePose.world_translation[2])
  expect(moved.freePose.world_rotation).toEqual(ready.freePose.world_rotation)
  await expect.poll(async () => (await state(page)).previewLoading, { timeout: 30000 }).toBe(false)
  expect((await design(page)).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await state(page)).preview?.connection_count ?? 0).toBeLessThan(ready.preview.connection_count)
  // Restore the requested exact pose and commit the complete checked set.
  await page.evaluate(pose => window.__nadocTest.clusterJoin.setFreePose(pose), fixture.pose)
  await expect(panel.locator('[data-join-apply]')).toBeEnabled({ timeout: 30000 })
  expect((await state(page)).preview.connection_count).toBeGreaterThan(1)
  page.on('request', r => { if (r.url().endsWith('/cluster-join/apply')) applied.push(r.postDataJSON()) })
  await panel.locator('[data-join-apply]').click()
  await expect(panel).toBeHidden({ timeout: 30000 })
  expect(applied).toHaveLength(1)
  expect(applied[0].world_translation).toEqual(fixture.pose.world_translation)
  const after = await design(page)
  expect(after.strands.filter(s => s.strand_type === 'scaffold')).toHaveLength(1)
  expect(after.feature_log.at(-1).op_kind).toBe('cluster-join')
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect((await design(page)).cluster_transforms).toEqual(before.cluster_transforms)
  expect((await design(page)).strands).toEqual(before.strands)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  expect((await design(page)).cluster_transforms).toEqual(after.cluster_transforms)
  expect((await design(page)).strands).toEqual(after.strands)
  expect(errors).toEqual([])
})
