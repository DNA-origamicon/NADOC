import { test, expect } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

test('audit rendered CPD beads against atomistic and standard thymine placement', async ({ page }) => {
  test.setTimeout(90_000)
  const measured = process.env.CPD_AUDIT_MEASURED !== 'false'
  await page.addInitScript(value => localStorage.setItem('nadoc.newPositioning.v3', String(value)), measured)
  const atomisticRequests = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname.endsWith('/design/atomistic')) atomisticRequests.push(url.searchParams.get('measured_positioning'))
  })
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.goto('/?doc=__e2e__cpd_bead_audit')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  expect(await page.evaluate(async () => (await import('/src/ui/new_positioning.js')).isNewPositioningOn())).toBe(measured)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.fill('#new-design-name', '__e2e__cpd_bead_audit')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  const files = process.env.CPD_AUDIT_FILES?.split(',') ?? ['tests/fixtures/cpd_2hb_1xt.nadoc']
  const output = []
  for (const file of files) {
    const design = JSON.parse(readFileSync(path.resolve('..', file), 'utf8'))
    const keys = design.photoproduct_junctions.flatMap(p => [p.base_key_1, p.base_key_2])
    design.metadata.name = '__e2e__cpd_bead_audit'
    design.feature_log = []; design.feature_log_cursor = -1
    for (const standard of [false, true]) {
      const copy = structuredClone(design)
      if (standard) { copy.photoproduct_junctions = []; copy.nucleotide_transforms = [] }
      await page.evaluate(async content => {
        await window.__nadocTest.nanoparticles.importDesign(content)
        await window.__nadocTest.setRepresentation('full')
      }, JSON.stringify(copy))
      const allBeads = await page.evaluate(async () => {
        const { baseKey, xbKey } = await import('/src/scene/base_ref.js')
        const renderer = window.__nadocTest.getDesignRenderer()
        return [...renderer.getBackboneEntries().map(e => ({ e, key: baseKey(e.nuc, e.nuc.copy ?? e.nuc.copy_k ?? 0) })),
          ...renderer.getXoverBeadEntries().map(e => ({ e, key: xbKey(e.xoId, e.simK) }))]
          .map(({ e, key }) => {
            const m = e.instMesh.matrix.clone()
            e.instMesh.getMatrixAt(e.id, m)
            return { key, position: e.instMesh.position.clone().setFromMatrixPosition(m).applyMatrix4(e.instMesh.matrixWorld).toArray() }
          })
      })
      const beads = await page.evaluate(async keys => {
        return window.__nadocTest.getDesignRenderer().getXoverBeadEntries()
          .filter(e => keys.includes(`__xb__:${e.xoId}:${e.simK}`)).map(e => {
            const m = e.instMesh.matrix.clone()
            e.instMesh.getMatrixAt(e.id, m)
            const position = e.instMesh.position.clone().setFromMatrixPosition(m).applyMatrix4(e.instMesh.matrixWorld)
            return { key: `__xb__:${e.xoId}:${e.simK}`, position: position.toArray() }
          })
      }, keys)
      const slabs = await page.evaluate(keys => {
        const renderer = window.__nadocTest.getDesignRenderer()
        return renderer.getXoverBeadEntries().filter(e => keys.includes(`__xb__:${e.xoId}:${e.simK}`)).map(e => {
          const info = renderer.xoverResidueInfo({ helix_id: '__xb__', crossover_id: e.xoId, k: e.simK })
          return { key: `__xb__:${e.xoId}:${e.simK}`, position: e.instMesh.position.clone().setFromMatrixPosition(info.slabMatrix).toArray() }
        })
      }, keys)
      expect(beads.length).toBe(keys.length)
      if (!standard) {
        const errors = await page.evaluate(async keys => {
          const { store } = await import('/src/state/store.js')
          const design = store.getState().currentDesign
          const renderer = window.__nadocTest.getDesignRenderer()
          const entries = renderer.getXoverBeadEntries().filter(e => keys.includes(`__xb__:${e.xoId}:${e.simK}`))
          const errors = []
          const originals = []
          for (const e of entries) {
            const key = `__xb__:${e.xoId}:${e.simK}`
            const geometry = design.photoproduct_junctions.find(p => p.representation_geometry?.[key]).representation_geometry[key]
            const tr = design.nucleotide_transforms.find(t => t.crossover_id === e.xoId && t.extra_base_k === e.simK)
            const q = e.instMesh.quaternion.clone().set(...tr.rotation)
            const pivot = e.instMesh.position.clone().set(...tr.pivot)
            const expected = xyz => e.instMesh.position.clone().set(...xyz).sub(pivot).applyQuaternion(q).add(pivot).add(e.instMesh.position.clone().set(...tr.translation))
            const target = { helix_id: '__xb__', crossover_id: e.xoId, k: e.simK }
            const info = renderer.xoverResidueInfo(target)
            originals.push({ target, info })
            errors.push(info.centroid.distanceTo(expected(geometry.backbone_position)))
            errors.push(e.instMesh.position.clone().setFromMatrixPosition(info.slabMatrix).distanceTo(expected(geometry.base_position)))
            // Exercise the real live move/rotate matrix path, then restore it.
            const delta = e.instMesh.matrix.clone().makeRotationZ(0.6).setPosition(1, -2, 3)
            renderer.applyXoverResidueMatrix(info, delta)
            const moved = renderer.xoverResidueInfo(target)
            errors.push(moved.centroid.distanceTo(info.centroid.clone().applyMatrix4(delta)))
            const expectedSlab = delta.clone().multiply(info.slabMatrix)
            errors.push(Math.max(...moved.slabMatrix.elements.map((v, i) => Math.abs(v - expectedSlab.elements[i]))))
            renderer.applyXoverResidueMatrix(info, delta.identity())
          }
          // Refresh from the abstraction must retain both independent projections.
          renderer.applyClusterCrossoverUpdate([])
          for (const { target, info } of originals) {
            const refreshed = renderer.xoverResidueInfo(target)
            errors.push(refreshed.centroid.distanceTo(info.centroid))
            errors.push(Math.max(...refreshed.slabMatrix.elements.map((v, i) => Math.abs(v - info.slabMatrix.elements[i]))))
          }
          return errors
        }, keys)
        expect(Math.max(...errors)).toBeLessThan(2e-6)
      }

      await page.evaluate(async () => window.__nadocTest.setRepresentation('ballstick'))
      await expect.poll(() => page.evaluate(keys => {
        let n = 0
        window.__nadocTest.getAtomisticRenderer().visitAtoms(a => {
          if (keys.includes(`__xb__:${a.crossover_id}:${a.extra_base_k}`)) n++
        })
        return n
      }, keys)).toBeGreaterThan(0)
      const atoms = await page.evaluate(keys => {
        const rows = []
        window.__nadocTest.getAtomisticRenderer().visitAtoms((a, p) => {
          const key = `__xb__:${a.crossover_id}:${a.extra_base_k}`
          if (keys.includes(key)) rows.push({ key, name: a.name, position: p.toArray() })
        })
        return rows
      }, keys)
      const allAtoms = await page.evaluate(async () => {
        const { atomBaseKey } = await import('/src/scene/base_ref.js')
        const rows = []
        window.__nadocTest.getAtomisticRenderer().visitAtoms((a, p) => {
          rows.push({ key: atomBaseKey(a), name: a.name, residue: a.residue, position: p.toArray() })
        })
        return rows
      })
      if (!standard) {
        // Cross-representation contract: actual rendered atoms, not the projector's own output.
        for (const bead of beads) {
          const own = atoms.filter(a => a.key === bead.key)
          const o5 = own.find(a => a.name === "O5'")
          expect(Math.hypot(...bead.position.map((v, i) => v - o5.position[i]))).toBeLessThan(2e-5)
          const ring = own.filter(a => ['N1', 'C2', 'N3', 'C4', 'C5', 'C6'].includes(a.name))
          expect(ring.length).toBe(6)
          const centroid = [0, 1, 2].map(i => ring.reduce((s, a) => s + a.position[i], 0) / 6)
          const slab = slabs.find(s => s.key === bead.key)
          expect(Math.hypot(...slab.position.map((v, i) => v - centroid[i]))).toBeLessThan(2e-5)
        }
      }
      output.push({ file, standard, measured_positioning: measured, beads, slabs, atoms, allBeads, allAtoms })
    }
  }
  expect(atomisticRequests.length).toBeGreaterThan(0)
  expect(atomisticRequests.every(value => value === String(measured))).toBe(true)
  writeFileSync(process.env.CPD_AUDIT_OUTPUT ?? '/tmp/cpd-bead-render-audit.json', JSON.stringify(output, null, 2))
})
