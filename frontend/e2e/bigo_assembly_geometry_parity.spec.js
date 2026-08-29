import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const PART = resolve(process.cwd(), '..', 'workspace', 'BigO.nadoc')
const ASSEMBLY = resolve(process.cwd(), '..', 'workspace', 'BigO-poly.nass')
test.skip(!existsSync(PART) || !existsSync(ASSEMBLY), 'BigO parity fixtures are missing')

async function load(page, assembly) {
  await page.goto(`/?doc=__e2e__bigo-geometry-${assembly ? 'assembly' : 'part'}&open=${assembly ? 'BigO-poly.nass' : 'BigO.nadoc'}&open-type=${assembly ? 'assembly' : 'design'}`)
  await page.waitForFunction(isAssembly => {
    const state = window.__NADOC_DBG__?.store.getState()
    return isAssembly
      ? state?.assemblyActive && (state.currentAssembly?.instances?.length ?? state.currentAssembly?.instances_v2?.length) === 1
      : !state?.assemblyActive && (state?.currentGeometry?.length ?? 0) > 0
  }, assembly, { timeout: 60_000 })
  if (assembly) {
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const dbg = window.__NADOC_DBG__
      const instances = dbg.store.getState().currentAssembly.instances
      const rebuilt = new Promise(resolve => dbg.assemblyRenderer.onRebuildComplete(resolve))
      await api.batchPatchInstances(instances.map(instance => ({ id: instance.id, representation: 'full' })))
      await rebuilt
    })
  } else {
    await page.evaluate(async () => window.__nadocTest.setRepresentation('full'))
  }
  await page.waitForFunction(() => {
    let found = false
    window.__NADOC_DBG__.scene.traverse(object => {
      if (object.name === 'baseSlabs' && (object.userData?.sharedBaseCount ?? object.count) > 0) found = true
    })
    return found
  }, null, { timeout: 90_000 })
  await page.waitForTimeout(500)
}

async function primitiveAudit(page, assembly) {
  return page.evaluate(isAssembly => {
    const THREE = window.__NADOC_DBG__.THREE
    const wanted = new Set([
      'backboneSpheres', 'backboneCubes', 'strandCones', 'baseSlabs',
      'slabBackboneConnectors', 'extensionFluorophores',
    ])
    const rows = {}
    const matrix = new THREE.Matrix4()
    const pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scale = new THREE.Vector3()
    window.__NADOC_DBG__.scene.traverse(object => {
      if (!wanted.has(object.name) || !object.isInstancedMesh) return
      const source = isAssembly ? object.userData.sharedBpXformData : object.instanceMatrix?.array
      const count = isAssembly ? object.userData.sharedBaseCount : object.count
      if (!source || !count) return
      const transforms = []
      for (let i = 0; i < count; i++) {
        matrix.fromArray(source, i * 16).decompose(pos, quat, scale)
        transforms.push({
          p: pos.toArray(), q: quat.toArray(), s: scale.toArray(),
        })
      }
      rows[object.name] = { count, transforms }
    })
    const arcs = []
    window.__NADOC_DBG__.scene.traverse(object => {
      if (/XoverArc/i.test(object.name)) arcs.push({
        name: object.name,
        vertices: object.geometry?.getAttribute?.('position')?.count ?? 0,
        visible: object.visible,
      })
    })
    return { rows, arcs }
  }, assembly)
}

async function crossoverColorAudit(page, mode) {
  await page.evaluate(next => window.__NADOC_DBG__.store.setState({ coloringMode: next }), mode)
  await page.waitForTimeout(100)
  return page.evaluate(() => {
    const histogram = {}
    window.__NADOC_DBG__.scene.traverse(object => {
      if (!/XoverArc/i.test(object.name)) return
      const attr = object.geometry?.getAttribute?.('color')
      if (!attr) return
      for (let i = 0; i < attr.count; i++) {
        const key = `${attr.getX(i).toFixed(5)},${attr.getY(i).toFixed(5)},${attr.getZ(i).toFixed(5)}`
        histogram[key] = (histogram[key] ?? 0) + 1
      }
    })
    return histogram
  })
}

test('BigO Full primitives and crossover arcs match their assembly source', async ({ browser }, testInfo) => {
  test.setTimeout(240_000)
  const audits = {}
  for (const [kind, assembly] of [['part', false], ['assembly', true]]) {
    const context = await browser.newContext()
    const page = await context.newPage()
    page.on('pageerror', error => console.log('BIGO_PAGE_ERROR', error.stack ?? error.message))
    page.on('console', message => {
      if (message.type() === 'error') console.log('BIGO_CONSOLE_ERROR', message.text())
    })
    await load(page, assembly)
    audits[kind] = await primitiveAudit(page, assembly)
    audits[kind].clusterArcColors = await crossoverColorAudit(page, 'cluster')
    audits[kind].overhangArcColors = await crossoverColorAudit(page, 'overhang-only')
    await context.close()
  }
  await testInfo.attach('bigo-geometry-parity.json', {
    body: JSON.stringify(audits, null, 2), contentType: 'application/json',
  })
  console.log('BIGO_GEOMETRY_COUNTS', JSON.stringify({
    part: Object.fromEntries(Object.entries(audits.part.rows).map(([k, v]) => [k, v.count])),
    assembly: Object.fromEntries(Object.entries(audits.assembly.rows).map(([k, v]) => [k, v.count])),
    partArcs: audits.part.arcs, assemblyArcs: audits.assembly.arcs,
  }))

  for (const [name, part] of Object.entries(audits.part.rows)) {
    const assembly = audits.assembly.rows[name]
    expect(assembly, `${name} missing from assembly`).toBeTruthy()
    expect(assembly.count, `${name} count`).toBe(part.count)
    // Compact assembly geometry is grouped helix/direction-wise, while the
    // design endpoint retains strand order. Compare multisets, not array order.
    const canonical = rows => rows.map(t => ['p', 'q', 's']
      .flatMap(field => t[field].map(value => value.toFixed(5))).join(','))
      .sort()
    expect(canonical(assembly.transforms), `${name} transform multiset`)
      .toEqual(canonical(part.transforms))
  }
  const visibleVertices = arcs => arcs
    .filter(arc => arc.visible).reduce((total, arc) => total + arc.vertices, 0)
  const allVertices = arcs => arcs.reduce((total, arc) => total + arc.vertices, 0)
  const hiddenAssemblyVertices = allVertices(audits.assembly.arcs) - visibleVertices(audits.assembly.arcs)
  expect(hiddenAssemblyVertices, 'periodic-seam crossover vertices').toBeGreaterThan(0)
  expect(visibleVertices(audits.assembly.arcs), 'visible assembly crossover vertices')
    .toBe(visibleVertices(audits.part.arcs) - hiddenAssemblyVertices)
  expect(allVertices(audits.assembly.arcs), 'all assembly crossover vertices')
    .toBe(allVertices(audits.part.arcs))
  expect(audits.assembly.clusterArcColors, 'cluster-colored crossover arcs')
    .toEqual(audits.part.clusterArcColors)
  expect(audits.assembly.overhangArcColors, 'overhang-only crossover arcs')
    .toEqual(audits.part.overhangArcColors)
})
