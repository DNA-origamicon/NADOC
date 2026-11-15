import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'

// Persistent artifacts: File > New saves only __e2e__short-flexible-host*.nadoc;
// global-teardown removes these files and any associated project revision stores.
// Autosave is disabled before boot; imported fixtures and JJ_Hinge are not saved.
// Session caching is disabled by playwright.config.js. The isolated Vite bridge
// credential and MD scratch are removed by global-teardown.js. Screenshots stay
// in Playwright's managed output directory.
for (const mode of [false, true, 'deleted']) {
  const sameCluster = mode === true
  test(`two-base scaffold marks ${sameCluster ? 'inside one cluster' : mode === 'deleted' ? 'across a deleted slot' : 'between clusters'}`, async ({ page }) => {
    test.setTimeout(90000)
    await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
    await page.goto(`/?doc=__e2e__short-flexible-${sameCluster}`)
    await page.waitForFunction(() => !!window.__nadocTest?.store)
    await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
    await page.click('#menu-file-new')
    await page.fill('#new-design-name', '__e2e__short-flexible-host')
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
    await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__short-flexible-host')
    const source = { name: '__e2e__short-flexible', version: '0.19.0', grid: 'square',
      helices: [{ grid_position: [0, 0], max_offset: 8 }, { grid_position: [sameCluster ? 1 : 9, 0], max_offset: 8 }],
      strands: [
        { is_scaffold: true, domains: [{ helix: 0, forward: true, start: 0, end: 8 }, { helix: 1, forward: false, start: 0, end: 8 }] },
        { domains: [{ helix: 0, forward: false, start: 0, end: 7 }] },
        { domains: [{ helix: 1, forward: true, start: 0, end: 7 }] },
      ] }
    if (sameCluster) {
      source.helices = source.helices.slice(0, 1)
      source.strands = [
        { is_scaffold: true, domains: [{ helix: 0, forward: true, start: 0, end: 8 }] },
        { domains: [{ helix: 0, forward: false, start: 0, end: 3 }] },
        { domains: [{ helix: 0, forward: false, start: 5, end: 8 }] },
      ]
    }
    if (mode === 'deleted') {
      source.helices = [0, 9, 18].map(x => ({ grid_position: [x, 0], max_offset: 8 }))
      source.strands = [
        { is_scaffold: true, domains: [
          { helix: 0, forward: true, start: 0, end: 8 },
          { helix: 1, forward: false, start: 0, end: 3, deletions: [0] },
          { helix: 2, forward: true, start: 0, end: 8 },
        ] },
        ...[0, 2].map(helix => ({ domains: [{ helix, forward: false, start: 0, end: 8 }] })),
      ]
    }
    const marks = await page.evaluate(async source => {
      const api = await import('/src/api/client.js')
      await api.importScadnanoDesign(JSON.stringify(source), source.name)
      const state = window.__nadocTest.store.getState()
      const scaffold = state.currentDesign.strands.find(s => s.strand_type === 'scaffold')
      if (source.helices.length === 3) return [1, 2].map(bp_index => ({ strand_id: scaffold.id, domain_index: 1, bp_index, direction: 'REVERSE' }))
      if (source.helices.length === 1) return [3, 4].map(bp_index => ({ strand_id: scaffold.id, domain_index: 0, bp_index, direction: 'FORWARD' }))
      return scaffold.domains.map((d, i) => ({ strand_id: scaffold.id, domain_index: i, bp_index: 7, direction: d.direction }))
    }, source)
    await page.waitForFunction(() => window.__nadocTest.store.getState().currentGeometry?.length > 0)
    await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
    const resolved = await page.evaluate(async marks => {
      const { flexibleRunForBead } = await import('/src/scene/design_queries.js')
      const state = window.__nadocTest.store.getState()
      const bead = state.currentGeometry.find(n => n.strand_id === marks[0].strand_id &&
        n.domain_index === marks[0].domain_index && n.bp_index === marks[0].bp_index)
      return flexibleRunForBead(state.currentDesign, state.currentGeometry, bead)
    }, marks)
    expect(resolved).toHaveLength(2)
    await page.evaluate(marks => window.__nadocTest.markFlexibleRun(marks), resolved)
    if (sameCluster) {
      await expect(page.getByText('flexible connections must be between two different cluster', { exact: true }).last()).toBeVisible()
      await page.getByRole('button', { name: 'OK', exact: true }).click()
    } else {
      await expect(page.locator('.toast-message').filter({ hasText: 'Marked 2-base flexible segment' })).toBeVisible()
    }
    const result = await page.evaluate(() => {
      const s = window.__nadocTest.store.getState()
      return { marks: s.currentDesign.flexible_segment_marks.length,
        connections: s.currentDesign.flexible_connections.length,
        beads: s.currentGeometry.filter(n => n.is_flexible_segment).length,
        features: s.currentDesign.feature_log.map(f => f.op_kind) }
    })
    expect(result.marks).toBe(sameCluster ? 0 : 2)
    expect(result.connections).toBe(sameCluster ? 0 : 1)
    expect(result.beads).toBe(sameCluster ? 0 : 2)
    expect(result.features).toEqual(sameCluster ? ['scadnano-import'] : ['scadnano-import', 'flexible-segment-mark'])
    await page.screenshot({ path: test.info().outputPath('two-base-flexible.png') })
    if (sameCluster) return
    const rendered = await page.evaluate(() => {
      const group = window.__nadocTest.scene.getObjectByName('flexibleArcs')
      return { visible: group.visible, counts: group.children
        .filter(m => m.name === 'flexSegmentBeads').map(m => m.count) }
    })
    expect(rendered).toEqual({ visible: true, counts: [2] })
    // Exercise the same relax-all controller used by the context menu. The
    // compact partial response must not recreate these beads in rigid meshes.
    await page.evaluate(async () => {
      const t = window.__nadocTest
      const api = await import('/src/api/client.js')
      const { initFlexRelax } = await import('/src/scene/flex_relax.js')
      await initFlexRelax({ store: t.store, api, designRenderer: t.getDesignRenderer(),
        clusterGizmo: t.clusterGizmo, isTranslateRotateActive: () => false }).relaxFlexible('all')
    })
    const relaxed = await page.evaluate(() => {
      const t = window.__nadocTest, s = t.store.getState()
      const marked = n => s.currentDesign.flexible_segment_marks.some(m =>
        m.strand_id === n.strand_id && m.domain_index === n.domain_index &&
        m.bp_index === n.bp_index && m.direction === n.direction)
      return { marks: s.currentDesign.flexible_segment_marks.length,
        flags: s.currentGeometry.filter(n => n.is_flexible_segment).length,
        rigid: t.getDesignRenderer().getBackboneEntries().filter(e => marked(e.nuc)).length,
        beads: t.scene.getObjectByName('flexibleArcs').children
          .filter(m => m.name === 'flexSegmentBeads').map(m => m.count),
        operation: s.currentDesign.feature_log.at(-1).op_kind }
    })
    expect(relaxed).toEqual({ marks: 2, flags: 2, rigid: 0, beads: [2], operation: 'flexible-relax' })
    await page.evaluate(async () => { const api = await import('/src/api/client.js'); await api.undo() })
    await page.evaluate(async () => { const api = await import('/src/api/client.js'); await api.undo() })
    await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign.flexible_segment_marks.length === 0)
  })
}

test('skipped import relaxation is explained in the app', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.goto('/?doc=__e2e__skip-relaxation-message')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__short-flexible-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__short-flexible-host')
  await page.evaluate(async () => {
    const { importRelaxationMessage } = await import('/src/ui/import_origami_options.js')
    const { showToast } = await import('/src/ui/toast.js')
    const api = await import('/src/api/client.js')
    const source = { name: '__e2e__nonplanar-import', version: '0.19.0', grid: 'square',
      helices: [[0, 0], [9, 0], [0, 9]].map(grid_position => ({ grid_position, max_offset: 8 })),
      strands: [{ is_scaffold: true, domains: [0, 1, 2].map(helix => ({ helix, forward: helix !== 1, start: 0, end: 8 })) }] }
    const result = await api.importScadnanoDesign(JSON.stringify(source), source.name, { relaxOrigami: true })
    if (result.relaxation?.status !== 'skipped') throw new Error('Expected unsupported 3D fit to be skipped')
    showToast(importRelaxationMessage(result.relaxation), 8000)
  })
  await expect(page.locator('.toast-message').filter({ hasText: 'Imported without relaxation.' })).toContainText('planar helix-axis layout')
})

// Read-only diagnosis of the user's existing legacy document. A rejected mark
// must not create an edited legacy copy; autosave stays disabled throughout.
test('JJ_Hinge rejects its saved intra-cluster run with an explanation', async ({ page }) => {
  test.setTimeout(120000)
  const fixture = path.resolve('../workspace/Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc')
  test.skip(!existsSync(fixture), 'Local user design')
  const saved = JSON.parse(readFileSync(fixture, 'utf8'))
  test.skip(saved.flexible_segment_marks?.length !== 2 || saved.flexible_connections?.length > 0,
    'The user has since separated clusters; this legacy rejection fixture no longer applies')
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.goto('/?doc=__e2e__jj-hinge-read-only')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__short-flexible-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__short-flexible-host')
  await page.evaluate(async fixture => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(fixture)
  }, fixture)
  // History snapshot copies hydrate asynchronously; compare authoring state
  // and feature records without these optional, read-only cached payloads.
  const digest = () => page.evaluate(async () => {
    const raw = new TextEncoder().encode(JSON.stringify(window.__nadocTest.store.getState().currentDesign, (key, value) =>
      ['post_state_gz_b64', 'design_snapshot'].includes(key) ? undefined : value))
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', raw)), b => b.toString(16).padStart(2, '0')).join('')
  })
  const before = await digest()
  console.log('JJ_Hinge read-only load completed')
  await page.evaluate(async () => {
    const design = window.__nadocTest.store.getState().currentDesign
    const marks = design.flexible_segment_marks.map(({ strand_id, domain_index, bp_index, direction }) =>
      ({ strand_id, domain_index, bp_index, direction }))
    if (marks.length !== 2 || design.flexible_connections.length) throw new Error('Local fixture changed; inspect it before adapting this diagnosis')
    await window.__nadocTest.markFlexibleRun(marks)
  })
  console.log('JJ_Hinge marking request completed')
  await expect(page.locator('.modal__body').filter({ hasText: 'flexible connections must be between two different cluster' })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('jj-hinge-rejection.png') })
  await page.getByRole('button', { name: 'OK', exact: true }).click()
  expect(await digest()).toBe(before)
})
