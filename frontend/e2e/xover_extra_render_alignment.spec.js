import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import * as THREE from 'three'

const FIXTURE = readFileSync(fileURLToPath(
  new URL('../../workspace/2hb_1xT.nadoc', import.meta.url)), 'utf8')

const SUGAR = new Set(["P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'"])
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
const centroid = atoms => atoms.reduce((s, a) => s.map((v, i) => v + a.pos[i]), [0, 0, 0])
  .map(v => v / atoms.length)
const DT_LOCAL = {
  N1: [0.3323, 0.3376, -0.0216], C2: [0.4595, 0.3874, -0.0278],
  N3: [0.5569, 0.2956, -0.0491],
}

function renderedAtomFrameOrigin(atoms) {
  const p = name => new THREE.Vector3(...atoms.find(a => a.name === name).pos)
  const l = name => new THREE.Vector3(...DT_LOCAL[name])
  const basis = (a, b, c) => {
    const x = b.clone().sub(a).normalize()
    const z = b.clone().sub(a).cross(c.clone().sub(a)).normalize()
    const y = z.clone().cross(x).normalize()
    return new THREE.Matrix4().makeBasis(x, y, z)
  }
  const localBasis = basis(l('N1'), l('C2'), l('N3'))
  const worldBasis = basis(p('N1'), p('C2'), p('N3'))
  const rotation = worldBasis.multiply(localBasis.invert())
  return l('N1').applyMatrix4(rotation).negate().add(p('N1')).toArray()
}

function renderedSlabConnectorErrors(r) {
  const bead = new THREE.Vector3(...r.bead)
  const slab = new THREE.Vector3(...r.slab)
  const slabQ = new THREE.Quaternion(...r.slabQuaternion)
  const slabScale = new THREE.Vector3(...r.slabScale)
  const localBead = bead.clone().sub(slab).applyQuaternion(slabQ.clone().invert())
  const corner = new THREE.Vector3(
    slabScale.x * 0.5, 0, (localBead.z < 0 ? -1 : 1) * slabScale.z * 0.5,
  ).applyQuaternion(slabQ).add(slab)

  const center = new THREE.Vector3(...r.slabConnector)
  const axis = new THREE.Vector3(0, 1, 0)
    .applyQuaternion(new THREE.Quaternion(...r.slabConnectorQuaternion))
  const half = r.slabConnectorScale[1] * 0.5
  const ends = [center.clone().addScaledVector(axis, half), center.clone().addScaledVector(axis, -half)]
  const direct = ends[0].distanceTo(bead) + ends[1].distanceTo(corner)
  const swapped = ends[1].distanceTo(bead) + ends[0].distanceTo(corner)
  const beadEnd = direct <= swapped ? ends[0] : ends[1]
  const slabEnd = direct <= swapped ? ends[1] : ends[0]
  return { beadEndError: beadEnd.distanceTo(bead), slabEndError: slabEnd.distanceTo(corner) }
}

test('2hb_1xT rendered Full inserts register with rendered atomistic residues', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/?doc=e2e-xover-extra-render-alignment')
  await page.waitForSelector('#canvas')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getRenderedXoverExtraGeometry
      ? Object.keys(window.__nadocTest.getRenderedXoverExtraGeometry()).length : 0),
  ).toBe(2)

  await page.evaluate(() => document.getElementById('menu-view-atomistic-ballstick')?.click())
  await expect.poll(() => page.evaluate(() => {
    let n = 0
    window.__nadocTest.getAtomisticRenderer().visitAtoms(a => {
      if (a.crossover_id != null && a.extra_base_k != null) n++
    })
    return n
  }), { timeout: 90_000 }).toBeGreaterThan(0)
  await page.evaluate(() => document.getElementById('menu-help-overlay-mode')?.click())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(true)

  const rendered = await page.evaluate(() => window.__nadocTest.getRenderedXoverExtraGeometry())
  const measurements = Object.fromEntries(Object.entries(rendered).map(([key, r]) => {
    const baseAtoms = r.atoms.filter(a => !SUGAR.has(a.name))
    const sugarAtoms = r.atoms.filter(a => SUGAR.has(a.name))
    const p = r.atoms.find(a => a.name === 'P')?.pos
    const c1 = r.atoms.find(a => a.name === "C1'")?.pos
    const baseCenter = centroid(baseAtoms)
    const sugarCenter = centroid(sugarAtoms)
    const atomFrameOrigin = renderedAtomFrameOrigin(r.atoms)
    const connectorErrors = renderedSlabConnectorErrors(r)
    return [key, {
      bead: r.bead, slab: r.slab, atomCount: r.atoms.length,
      baseCenter, sugarCenter, atomFrameOrigin, p, c1,
      beadToAtomFrameOrigin: dist(r.bead, atomFrameOrigin),
      beadToP: dist(r.bead, p), beadToSugarCenter: dist(r.bead, sugarCenter),
      slabToBaseCenter: dist(r.slab, baseCenter),
      ...connectorErrors,
    }]
  }))
  console.log('RENDERED_XOVER_ALIGNMENT=' + JSON.stringify(measurements))
  expect(Object.keys(measurements)).toHaveLength(2)
  for (const m of Object.values(measurements)) {
    expect(m.atomCount).toBeGreaterThanOrEqual(20)
    expect(m.bead.every(Number.isFinite)).toBe(true)
    expect(m.slab.every(Number.isFinite)).toBe(true)
    expect(m.beadToAtomFrameOrigin, JSON.stringify(m)).toBeLessThan(2e-4)
    expect(m.slabToBaseCenter, JSON.stringify(m)).toBeLessThan(2e-4)
    expect(m.beadEndError, JSON.stringify(m)).toBeLessThan(2e-4)
    expect(m.slabEndError, JSON.stringify(m)).toBeLessThan(2e-4)
  }
})
