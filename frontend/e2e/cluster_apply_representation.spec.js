import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const FIXTURE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/smoke/smoke_design.nadoc',
)
const delta = (after, before) => after.map((value, index) => value - before[index])

async function readPhysicalClusterParts(page, clusterId) {
  return page.evaluate(id => {
    const api = window.__nadocTest
    const design = api.store.getState().currentDesign
    const cluster = design.cluster_transforms.find(item => item.id === id)
    const helixIds = new Set(cluster.helix_ids)
    const domainIds = cluster.domain_ids?.length
      ? new Set(cluster.domain_ids.map(item => `${item.strand_id}:${item.domain_index}`))
      : null
    const inCluster = nuc => helixIds.has(nuc.helix_id) &&
      (!domainIds || domainIds.has(`${nuc.strand_id}:${nuc.domain_index}`))
    const ctrl = api.getDesignRenderer().getHelixCtrl()
    const Matrix4 = ctrl.root.matrix.constructor
    const Vector3 = ctrl.root.position.constructor
    const recordMatrix = (target, partKey, mesh, instanceId) => {
      const matrix = new Matrix4()
      mesh.getMatrixAt(instanceId, matrix)
      target[`${partKey}:center`] = new Vector3(0, 0, 0).applyMatrix4(matrix).toArray()
      target[`${partKey}:axis-x`] = new Vector3(1, 0, 0).applyMatrix4(matrix).toArray()
      target[`${partKey}:axis-y`] = new Vector3(0, 1, 0).applyMatrix4(matrix).toArray()
      target[`${partKey}:axis-z`] = new Vector3(0, 0, 1).applyMatrix4(matrix).toArray()
    }
    const recordCenter = (target, partKey, mesh, instanceId) => {
      const matrix = new Matrix4()
      mesh.getMatrixAt(instanceId, matrix)
      target[`${partKey}:center`] = new Vector3().setFromMatrixPosition(matrix).toArray()
    }
    const recordAxialMatrix = (target, partKey, mesh, instanceId) => {
      const matrix = new Matrix4()
      mesh.getMatrixAt(instanceId, matrix)
      target[`${partKey}:center`] = new Vector3(0, 0, 0).applyMatrix4(matrix).toArray()
      target[`${partKey}:axis-y`] = new Vector3(0, 1, 0).applyMatrix4(matrix).toArray()
    }
    const key = (nuc, copy = 0) =>
      `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}:${copy}`
    const output = { beads: {}, slabs: {}, slabConnectors: {}, cones: {}, axes: {} }
    for (const entry of ctrl.backboneEntries) {
      if (inCluster(entry.nuc)) recordCenter(
        output.beads, key(entry.nuc, entry._copy), entry.instMesh, entry.id)
    }
    for (const slab of ctrl.slabEntries) {
      if (!inCluster(slab.nuc)) continue
      const partKey = key(slab.nuc, slab._copy)
      recordMatrix(output.slabs, partKey, slab.instMesh, slab.id)
      recordAxialMatrix(output.slabConnectors, partKey, slab.connectorMesh, slab.connectorId)
    }
    for (const cone of ctrl.coneEntries) {
      if (!inCluster(cone.fromNuc) || !inCluster(cone.toNuc)) continue
      const partKey = `${key(cone.fromNuc)}>${key(cone.toNuc)}`
      recordAxialMatrix(output.cones, partKey, cone.instMesh, cone.id)
    }
    for (const arrow of ctrl.getAxisArrows()) {
      if (!helixIds.has(arrow.helixId)) continue
      if (!domainIds) {
        output.axes[`${arrow.helixId}:start`] = arrow.aStart.toArray()
        output.axes[`${arrow.helixId}:end`] = arrow.aEnd.toArray()
      }
      for (const [index, segment] of (arrow.segments ?? []).entries()) {
        if (domainIds && !domainIds.has(`${segment.strandId}:${segment.domainIndex}`)) continue
        output.axes[`${arrow.helixId}:segment:${index}:start`] = segment.wsStart.toArray()
        output.axes[`${arrow.helixId}:segment:${index}:end`] = segment.wsEnd.toArray()
      }
    }
    return output
  }, clusterId)
}

function expectEveryPartTranslated(before, after, translation) {
  for (const kind of Object.keys(before)) {
    const beforeParts = before[kind]
    const afterParts = after[kind]
    expect(Object.keys(afterParts), `${kind} membership`).toEqual(Object.keys(beforeParts))
    expect(Object.keys(beforeParts).length, `${kind} has measured parts`).toBeGreaterThan(0)
    for (const [part, beforePosition] of Object.entries(beforeParts)) {
      expect(delta(afterParts[part], beforePosition), `${kind} ${part}`).toEqual([
        expect.closeTo(translation[0], 5),
        expect.closeTo(translation[1], 5),
        expect.closeTo(translation[2], 5),
      ])
    }
  }
}

function expectEveryPartRestored(before, after) {
  expectEveryPartTranslated(before, after, [0, 0, 0])
}

function expectEveryPartTransformed(before, after, transform) {
  for (const kind of Object.keys(before)) {
    expect(Object.keys(after[kind]), `${kind} membership`).toEqual(Object.keys(before[kind]))
    expect(Object.keys(before[kind]).length, `${kind} has measured parts`).toBeGreaterThan(0)
    for (const [part, beforePosition] of Object.entries(before[kind])) {
      const expected = transform(beforePosition)
      expect(after[kind][part], `${kind} ${part}`).toEqual([
        expect.closeTo(expected[0], 5),
        expect.closeTo(expected[1], 5),
        expect.closeTo(expected[2], 5),
      ])
    }
  }
}

async function loadFixture(page) {
  await page.goto('/')
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async path => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
    await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const leftPanel = document.getElementById('left-panel')
    leftPanel?.classList.remove('locked-hidden')
    document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(button => {
      button.disabled = false
    })
    const sidebar = window.__leftSidebar
    sidebar?.refresh?.()
    sidebar?.selectTab?.('feature-log')
    if (sidebar?.isCollapsed?.()) sidebar.toggleCollapsed()
  }, FIXTURE)
  await page.waitForFunction(() => window.__nadocTest.viewerDiagnostic().backboneEntries > 0)
  return page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.cluster_transforms[0].id)
}

async function latestClusterFeatureIndex(page) {
  return page.evaluate(() => {
    const design = window.__nadocTest.store.getState().currentDesign
    return design.feature_log.findLastIndex(entry => entry.feature_type === 'cluster_op')
  })
}

async function clickFeatureDelete(page, featureIndex) {
  const row = page.locator(`[data-fl-row="${featureIndex + 1}"]`)
  await row.getByTitle('Delete this feature').click()
  await expect.poll(() => page.evaluate(index => {
    const design = window.__nadocTest.store.getState().currentDesign
    return design.feature_log[index]?.feature_type === 'cluster_op'
  }, featureIndex)).toBe(false)
}

async function clickFeatureRevert(page, featureIndex) {
  const row = page.locator(`[data-fl-row="${featureIndex + 1}"]`)
  await row.getByTitle(/Revert to before this move\/rotate/).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Revert' }).click()
  await expect.poll(() => page.evaluate(index =>
    window.__nadocTest.store.getState().currentDesign.feature_log.length <= index,
  featureIndex)).toBe(true)
}

test('Feature Log delete restores every translated cluster part after a representation round-trip', async ({ page }) => {
  const clusterId = await loadFixture(page)
  await page.evaluate(id => window.__nadocTest.activateDesignMoveTool(id), clusterId)
  const before = await page.evaluate(id => window.__nadocTest.getClusterGizmoState(id).beadCentroid, clusterId)
  const physicalBefore = await readPhysicalClusterParts(page, clusterId)

  await page.evaluate(() => {
    for (const [id, value] of [['mr-tx', 3], ['mr-ty', 4], ['mr-tz', 5]]) {
      const input = document.getElementById(id)
      input.value = String(value)
    }
    document.getElementById('mr-tz').dispatchEvent(new Event('change', { bubbles: true }))
  })
  const preview = await page.evaluate(id => window.__nadocTest.getClusterGizmoState(id).beadCentroid, clusterId)
  expect(delta(preview, before)).toEqual([
    expect.closeTo(3, 6), expect.closeTo(4, 6), expect.closeTo(5, 6),
  ])
  expectEveryPartTranslated(physicalBefore, await readPhysicalClusterParts(page, clusterId), [3, 4, 5])

  await page.evaluate(() => document.getElementById('mr-apply-btn').click())
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.store.getState().translateRotateActive)).toBe(false)
  const applied = await page.evaluate(id => window.__nadocTest.getClusterGizmoState(id).beadCentroid, clusterId)
  expect(delta(applied, before)).toEqual([
    expect.closeTo(3, 6), expect.closeTo(4, 6), expect.closeTo(5, 6),
  ])
  expectEveryPartTranslated(physicalBefore, await readPhysicalClusterParts(page, clusterId), [3, 4, 5])

  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  await expect.poll(() => page.evaluate(() => {
    let count = 0
    window.__nadocTest.getAtomisticRenderer().visitAtoms(() => { count++ })
    return count
  }), { timeout: 60_000 }).toBeGreaterThan(0)
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(true)

  const roundTrip = await page.evaluate(id => window.__nadocTest.getClusterGizmoState(id).beadCentroid, clusterId)
  expect(delta(roundTrip, before)).toEqual([
    expect.closeTo(3, 6), expect.closeTo(4, 6), expect.closeTo(5, 6),
  ])
  expectEveryPartTranslated(physicalBefore, await readPhysicalClusterParts(page, clusterId), [3, 4, 5])

  const featureIndex = await latestClusterFeatureIndex(page)
  expect(featureIndex).toBeGreaterThanOrEqual(0)
  await clickFeatureDelete(page, featureIndex)
  expectEveryPartRestored(physicalBefore, await readPhysicalClusterParts(page, clusterId))
})

test('committed cluster rotation rigidly moves every rendered sub-part and Feature Log revert restores it', async ({ page }) => {
  const clusterId = await loadFixture(page)
  await page.evaluate(id => window.__nadocTest.activateDesignMoveTool(id), clusterId)
  const pivot = await page.evaluate(id => window.__nadocTest.getClusterGizmoState(id).gizmoPos, clusterId)
  const physicalBefore = await readPhysicalClusterParts(page, clusterId)
  const angle = Math.PI / 6
  const rotateAboutPivot = ([x, y, z]) => {
    const dx = x - pivot[0], dy = y - pivot[1]
    return [
      pivot[0] + dx * Math.cos(angle) - dy * Math.sin(angle),
      pivot[1] + dx * Math.sin(angle) + dy * Math.cos(angle),
      z,
    ]
  }

  await page.evaluate(() => {
    const input = document.getElementById('mr-rz')
    input.value = '30'
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  expectEveryPartTransformed(
    physicalBefore, await readPhysicalClusterParts(page, clusterId), rotateAboutPivot)

  await page.evaluate(() => document.getElementById('mr-apply-btn').click())
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.store.getState().translateRotateActive)).toBe(false)
  expectEveryPartTransformed(
    physicalBefore, await readPhysicalClusterParts(page, clusterId), rotateAboutPivot)

  const featureIndex = await latestClusterFeatureIndex(page)
  expect(featureIndex).toBeGreaterThanOrEqual(0)
  await clickFeatureRevert(page, featureIndex)
  expectEveryPartRestored(physicalBefore, await readPhysicalClusterParts(page, clusterId))
})
