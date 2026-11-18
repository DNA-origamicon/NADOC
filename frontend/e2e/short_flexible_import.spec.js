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
    // Exercise the context-menu controller, including authoritative network
    // closure and an unchanged fixed reference, through real API/store/rendering.
    const beforePoses = await page.evaluate(() => window.__nadocTest.store.getState()
      .currentDesign.cluster_transforms)
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
    const solved = await page.evaluate(() => {
      const design = window.__nadocTest.store.getState().currentDesign
      return { poses: design.cluster_transforms, report: design.feature_log.at(-1).params.relaxation }
    })
    expect(solved.report.converged).toBe(true)
    expect(solved.report.solver).toBe('rigid-flex-staged-contact-v2')
    expect(solved.report.contacts.max_penetration_nm).toBeLessThanOrEqual(.001)
    expect(solved.report.max_excess_nm).toBeLessThanOrEqual(.001)
    for (const id of solved.report.fixed_cluster_ids) {
      expect(solved.poses.find(c => c.id === id)).toEqual(beforePoses.find(c => c.id === id))
    }
    await page.keyboard.press('f')
    await page.screenshot({ path: test.info().outputPath('two-base-relaxed.png') })
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

test('JJ_Hinge actual relax all and rendered clearance', async ({ page }) => {
  test.setTimeout(360000)
  const fixture = path.resolve('../workspace/Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc')
  test.skip(!existsSync(fixture), 'Local user design unavailable')
  const original = readFileSync(fixture, 'utf8')
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.goto('/?doc=__e2e__jj-network-read-only')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__jj-network-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async fixture => {
    const api = await import('/src/api/client.js')
    window.__nadocTest.pauseViewerRenderingForTest()
    await api.loadDesign(fixture)
    console.log('JJ loaded')
    window.__nadocTest.setRepresentation('full')
  }, fixture)
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentGeometry?.length > 1000)
  await page.keyboard.press('f')
  await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
  await page.screenshot({ path: test.info().outputPath('jj-hinge-read-only.png') })
  console.log('JJ before screenshot captured')
  const count = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)
  page.on('response', async response => {
    if (response.url().includes('flexible') && response.request().method() === 'POST') console.log('JJ relax response', response.status())
  })
  await page.evaluate(async () => {
    const t = window.__nadocTest
    const api = await import('/src/api/client.js')
    const { initFlexRelax } = await import('/src/scene/flex_relax.js')
    await initFlexRelax({ store: t.store, api, designRenderer: t.getDesignRenderer(),
      isTranslateRotateActive: () => false }).relaxFlexible('all')
  })
  await page.keyboard.press('f')
  await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
  await page.screenshot({ path: test.info().outputPath('jj-hinge-after.png') })
  console.log('JJ visible messages', await page.locator('.toast-message').allTextContents())
  const result = await page.evaluate(() => {
    const d = window.__nadocTest.store.getState().currentDesign
    return { count: d.feature_log.length, report: d.feature_log.at(-1).params.relaxation }
  })
  console.log('JJ actual result', JSON.stringify(result))
  const refreshed = await page.evaluate(async () => {
    const t = window.__nadocTest
    const key = n => [n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0].join(':')
    const before = new Map(t.getDesignRenderer().getBackboneEntries().map(e => [key(e.nuc), e.pos.toArray()]))
    const api = await import('/src/api/client.js')
    await api.getGeometry()
    let maximum = 0
    for (const e of t.getDesignRenderer().getBackboneEntries()) {
      const p = before.get(key(e.nuc))
      if (p) maximum = Math.max(maximum, Math.hypot(...e.pos.toArray().map((v, i) => v-p[i])))
    }
    return maximum
  })
  console.log('JJ rendered coordinate change after authoritative refresh', refreshed)
  expect(refreshed).toBeLessThan(.001)
  const frame = await page.evaluate(() => {
    const positions = window.__nadocTest.getDesignRenderer().getBackboneEntries().map(e => e.pos.toArray())
    const low = [0,1,2].map(i => Math.min(...positions.map(p => p[i])))
    const high = [0,1,2].map(i => Math.max(...positions.map(p => p[i])))
    return { center: low.map((v,i) => (v+high[i])/2), span: Math.max(...low.map((v,i) => high[i]-v)) }
  })
  for (const [name, direction, up] of [
    ['front', [0,0,1], [0,1,0]], ['side', [1,0,0], [0,1,0]],
    ['top', [0,1,0], [0,0,1]], ['oblique', [1,1,1], [0,1,0]],
  ]) {
    await page.evaluate(({ frame, direction, up }) => {
      const t = window.__nadocTest
      const norm = Math.hypot(...direction)
      t.applyCameraPoseForTest({ target: frame.center,
        position: frame.center.map((v,i) => v+direction[i]/norm*frame.span*1.8), up, fov: 40 })
      t.renderViewerFrameForTest()
    }, { frame, direction, up })
    await page.screenshot({ path: test.info().outputPath('jj-hinge-'+name+'.png') })
  }

  expect(result.count).toBe(count + 1)
  expect(result.report.solver).toBe('rigid-flex-staged-contact-v2')
  expect(result.report.converged).toBe(true)
  expect(result.report.contacts.max_penetration_nm).toBeLessThanOrEqual(.001)
  expect(result.report.max_excess_nm).toBeLessThanOrEqual(.001)
  const motion = await page.evaluate(async () => {
    const t = window.__nadocTest
    const d = t.store.getState().currentDesign
    const cluster = d.cluster_transforms.find(c => c.name === 'Geometry Cluster 2')
    return { connections: d.flexible_connections.length, ...(await t.activateDesignMoveTool(cluster.id)) }
  })
  expect(result.report.connections).toHaveLength(motion.connections)
  expect(motion.active).toBe(true)
  expect(motion.pivotOptions).toContain('ssdna')
  await page.selectOption('#mr-pivot-sel', 'ssdna')
  await expect(page.locator('#mr-pivot-sel')).toHaveValue('ssdna')

  // History must discard the live transform before applying its committed-pose
  // delta. Compare every rendered backbone against an authoritative rebuild.
  await page.selectOption('#mr-pivot-sel', 'centroid')
  const preview = async () => {
    await page.evaluate(() => {
      const t = window.__nadocTest
      window.__previewBefore = t.getDesignRenderer().getBackboneEntries().map(e => e.pos.toArray())
    })
    await page.fill('#mr-tx', '3')
    await page.locator('#mr-tx').dispatchEvent('change')
    expect(await page.evaluate(() => {
      const entries = window.__nadocTest.getDesignRenderer().getBackboneEntries()
      return Math.max(0, ...entries.map((e, j) => Math.hypot(...e.pos.toArray().map((v, i) => v-window.__previewBefore[j][i]))))
    })).toBeGreaterThan(.001)
  }
  const awaitHistoryPaint = async targetCount => page.evaluate(target => {
    const store = window.__nadocTest.store
    let geometry = store.getState().currentGeometry
    window.__historyPaintDone = false
    const unsubscribe = store.subscribe(state => {
      const replaced = state.currentGeometry !== geometry
      geometry = state.currentGeometry
      if (replaced && state.currentDesign?.feature_log.length === target) {
        window.__historyPaintDone = true; unsubscribe()
      }
    })
  }, targetCount)
  const parity = async () => page.evaluate(async () => {
    const t = window.__nadocTest, api = await import('/src/api/client.js')
    const key = n => [n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0].join(':')
    const before = new Map(t.getDesignRenderer().getBackboneEntries().map(e => [key(e.nuc), e.pos.toArray()]))
    await api.getGeometry()
    return Math.max(0, ...t.getDesignRenderer().getBackboneEntries().map(e => {
      const p = before.get(key(e.nuc))
      return p ? Math.hypot(...e.pos.toArray().map((v, i) => v-p[i])) : Infinity
    }))
  })
  await preview()
  await awaitHistoryPaint(count)
  await page.locator('.menu-item').filter({ hasText: 'Edit' }).first().hover()
  await page.click('#menu-edit-undo')
  await page.waitForFunction(count => !window.__nadocTest.store.getState().translateRotateActive
    && window.__nadocTest.store.getState().currentDesign.feature_log.length === count, count)
  await page.waitForFunction(() => window.__historyPaintDone)
  expect(await parity()).toBeLessThan(.001)
  if (process.env.NADOC_JJ_REVIEW_DIR) {
    await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
    await page.screenshot({ path: path.join(process.env.NADOC_JJ_REVIEW_DIR, 'after-undo.png') })
  }
  await page.evaluate(async () => {
    const t = window.__nadocTest
    await t.activateDesignMoveTool(t.store.getState().currentDesign.cluster_transforms.find(c => c.name === 'Geometry Cluster 2').id)
  })
  await preview()
  await awaitHistoryPaint(count + 1)
  await page.evaluate(() => document.activeElement?.blur())
  await page.keyboard.press('Control+y')
  await page.waitForFunction(count => !window.__nadocTest.store.getState().translateRotateActive
    && window.__nadocTest.store.getState().currentDesign.feature_log.length === count + 1, count)
  await page.waitForFunction(() => window.__historyPaintDone)
  expect(await parity()).toBeLessThan(.001)
  console.log('JJ undo/redo preview parity passed; no preview feature recorded')

  await page.evaluate(async () => {
    const t = window.__nadocTest
    await t.activateDesignMoveTool(t.store.getState().currentDesign.cluster_transforms.find(c => c.name === 'Geometry Cluster 2').id)
  })
  await preview()
  await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
  await page.getByRole('button', { name: 'repair', exact: true }).first().click()
  const repair = page.getByRole('dialog').filter({ hasText: 'Check and repair part recipe' })
  await repair.getByRole('button', { name: 'Refresh displayed geometry', exact: true }).click()
  await expect(repair).toContainText('Display rebuilt from published geometry; recipe unchanged.')
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)).toBe(count + 1)
  expect(await parity()).toBeLessThan(.001)
  await repair.getByRole('button', { name: 'Close', exact: true }).click()
  if (process.env.NADOC_JJ_REVIEW_DIR) {
    await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
    await page.screenshot({ path: path.join(process.env.NADOC_JJ_REVIEW_DIR, 'after-display-recovery.png') })
  }

  expect(readFileSync(fixture, 'utf8')).toBe(original)
})


test('JJ_Hinge tethered collision toggle', async ({ page }) => {
  test.setTimeout(180000)
  const fixture = path.resolve('../workspace/Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc')
  test.skip(!existsSync(fixture), 'Local user design unavailable')
  const original = readFileSync(fixture, 'utf8')
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.goto('/?doc=__e2e__jj-contact-read-only')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__jj-contact-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__jj-contact-host')
  await page.evaluate(async fixture => {
    const t = window.__nadocTest, api = await import('/src/api/client.js')
    t.pauseViewerRenderingForTest()
    await api.loadDesign(fixture)
    const relaxed=t.store.getState().currentDesign.feature_log.findLastIndex(f => f.params?.relaxation)
    if (relaxed >= 0) await api.seekFeatures(relaxed)
    t.setRepresentation('full')
    if (relaxed < 0) {
      const { initFlexRelax } = await import('/src/scene/flex_relax.js')
      await initFlexRelax({ store: t.store, api, designRenderer: t.getDesignRenderer(),
        isTranslateRotateActive: () => false }).relaxFlexible('all')
    }
  }, fixture)
  await page.route('**/design/flexible-connections', async route => {
    await new Promise(r=>setTimeout(r,350)); await route.continue()
  })
  await page.keyboard.press('m')
  await page.evaluate(() => {
    const t=window.__nadocTest
    const id=t.store.getState().currentDesign.cluster_transforms.find(c=>c.name==='Geometry Cluster 2').id
    t.selectRefsForTest([{kind:'cluster',id}])
  })
  await expect(page.locator('#mr-pivot-sel option[value=ssdna]')).toHaveCount(1)
  await page.keyboard.press('f')
  const displayBefore = await page.evaluate(() => window.__nadocTest.getDesignRenderer().getBackboneEntries().map(e => e.pos.toArray()))
  const count = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)
  await page.selectOption('#mr-pivot-sel', 'ssdna')
  await page.waitForFunction(() => window.__nadocTest.clusterGizmo.isTetherConstraintActive())
  await expect(page.locator('#mr-tether-collisions')).toBeChecked()
  const initialAngle = await page.inputValue('#mr-rx')
  const collisionExercise = async (degrees, enabled = true) => {
    if (enabled) await page.check('#mr-tether-collisions')
    else await page.uncheck('#mr-tether-collisions')
    return page.evaluate(async degrees => {
      const t = window.__nadocTest, s = t.store.getState()
      const { buildContactBodies, duplexGap } = await import('/src/scene/tether_contacts.js')
      const { flexAnchorKey } = await import('/src/scene/design_queries.js')
      const { Vector3, Quaternion } = await import('/node_modules/three/build/three.module.js')
      const clusters = s.currentDesign.cluster_transforms
      const cluster = clusters.find(c => c.name === 'Geometry Cluster 2')
      const fixed = clusters.find(c => c.name === 'Geometry Cluster 1')
      const before = buildContactBodies(s.currentDesign, s.currentGeometry)
      const start = performance.now()
      const input = document.getElementById('mr-rx')
      input.value = String(degrees)
      input.dispatchEvent(new Event('change', { bubbles: true }))
      const elapsed = performance.now() - start
      const pending = t.clusterGizmo.getAllPendingTransforms()
      const after = buildContactBodies(s.currentDesign, s.currentGeometry, pending)
      let worsening = 0, tested = 0
      for (let i = 0; i < before.length; i++) for (let j = 0; j < i; j++) {
        if (before[i].owner === before[j].owner) continue
        worsening = Math.max(worsening, Math.min(0, duplexGap(before[i], before[j])) - duplexGap(after[i], after[j]))
        tested++
      }
      const positions = new Map(s.currentGeometry.map(n => [`${n.helix_id}:${n.bp_index}:${n.direction}`, n.backbone_position]))
      const point = (anchor, id, live) => {
        const out = new Vector3(...positions.get(flexAnchorKey(anchor, s.currentDesign)))
        const base = clusters.find(c => c.id === id), pose = pending.find(p => p.clusterId === id)
        if (!live || !pose) return out
        return out.sub(new Vector3(...base.pivot)).sub(new Vector3(...base.translation))
          .applyQuaternion(new Quaternion(...base.rotation).invert())
          .add(new Vector3(...base.pivot)).sub(new Vector3(...pose.pivot))
          .applyQuaternion(new Quaternion(...pose.rotation))
          .add(new Vector3(...pose.pivot)).add(new Vector3(...pose.translation))
      }
      const displayed = new Map(t.getDesignRenderer().getBackboneEntries().map(e =>
        [`${e.nuc.helix_id}:${e.nuc.bp_index}:${e.nuc.direction}`,e.pos]))
      let stretch = 0, displayError = 0
      for (const e of s.currentDesign.flexible_connections) {
        const distance = live => point(e.anchor_a,e.cluster_a_id,live).distanceTo(point(e.anchor_b,e.cluster_b_id,live))
        stretch = Math.max(stretch, distance(true) - Math.max(e.contour_length_nm,distance(false)))
        for (const [anchor,id] of [[e.anchor_a,e.cluster_a_id],[e.anchor_b,e.cluster_b_id]])
          displayError = Math.max(displayError, point(anchor,id,true).distanceTo(displayed.get(flexAnchorKey(anchor,s.currentDesign))))
      }
      const followers = pending.filter(p => p.clusterId !== cluster.id && p.clusterId !== fixed.id)
        .map(p => {
          const c = clusters.find(c => c.id === p.clusterId)
          return new Vector3(...p.translation).distanceTo(new Vector3(...c.translation)) +
            new Quaternion(...p.rotation).angleTo(new Quaternion(...c.rotation))
        })
      return { worsening, stretch, displayError, tested, elapsed, followers,
        fixedMoved: pending.some(p => p.clusterId === fixed.id), angle: Number(input.value),
        features: s.currentDesign.feature_log.length }
    }, degrees)
  }
  const restartMove = async () => {
    await page.click('#mr-cancel-btn')
    await page.waitForFunction(() => !window.__nadocTest.store.getState().translateRotateActive)
    await page.evaluate(async () => {
      const t = window.__nadocTest
      await t.activateDesignMoveTool(t.store.getState().currentDesign.cluster_transforms.find(c => c.name === 'Geometry Cluster 2').id)
    })
    await page.selectOption('#mr-pivot-sel', 'ssdna')
    await page.waitForFunction(() => window.__nadocTest.clusterGizmo.isTetherConstraintActive())
  }
  const exerciseLive = () => page.evaluate(async renderFrames => {
    const t=window.__nadocTest
    const {Quaternion,Vector3}=await import('/node_modules/three/build/three.module.js')
    const tc=t.scene.children.find(n=>n.controls?.object).controls
    const canvas=document.querySelector('canvas'),gl=canvas.getContext('webgl2')
    if(renderFrames)for(let i=0;i<2;i++){t.renderViewerFrameForTest();gl.finish();await new Promise(requestAnimationFrame)}
    const initial=tc.object.quaternion.clone();let maxAngle=0
    tc.dispatchEvent({type:'dragging-changed',value:true})
    const times=[]
    for(let i=0;i<60;i++){
      await new Promise(r=>setTimeout(r,0))
      const start=performance.now()
      tc.object.quaternion.premultiply(new Quaternion().setFromAxisAngle(new Vector3(1,0,0),(i<30?1:-1)*([.1,.5,1][Math.floor(i/10)%3])*Math.PI/180))
      tc.dispatchEvent({type:'change'})
      maxAngle=Math.max(maxAngle,initial.angleTo(tc.object.quaternion))
      if(renderFrames){t.renderViewerFrameForTest();gl.finish()}
      times.push(performance.now()-start)
    }
    tc.dispatchEvent({type:'dragging-changed',value:false})
    times.sort((a,b)=>a-b)
    const info=gl?.getExtension('WEBGL_debug_renderer_info')
    return {maxAngle,median:times[30],p95:times[57],max:times[59],times,renderer:info?gl.getParameter(info.UNMASKED_RENDERER_WEBGL):null}
  },!!process.env.NADOC_JJ_RENDER_FRAMES)
  const live=await exerciseLive()
  console.log('JJ live updates',JSON.stringify(live))
  expect(live.max).toBeLessThan(200)
  expect(live.maxAngle).toBeGreaterThan(.001)
  const liveGeometry=await collisionExercise(Number(await page.inputValue('#mr-rx')))
  expect(liveGeometry.worsening).toBeLessThanOrEqual(.0011)
  expect(liveGeometry.stretch).toBeLessThanOrEqual(.0011)
  expect(liveGeometry.displayError).toBeLessThan(1e-4)
  await restartMove()
  const collisionOn = await collisionExercise(Number(initialAngle) + 5)
  console.log('JJ positive', initialAngle, JSON.stringify(collisionOn))
  expect(collisionOn.worsening).toBeLessThanOrEqual(.00101)
  expect(collisionOn.displayError).toBeLessThan(1e-4)
  expect(collisionOn.stretch).toBeLessThanOrEqual(.00101)
  expect(collisionOn.followers).toHaveLength(6)
  expect(collisionOn.followers.filter(d => d > 1e-5).length >= 2).toBe(true)
  expect(collisionOn.fixedMoved).toBe(false)
  expect(collisionOn.angle).toBeGreaterThan(Number(initialAngle) + .1)
  expect(collisionOn.features).toBe(count)
  await page.locator('#mr-tether-collisions').scrollIntoViewIfNeeded()
  await page.evaluate(() => {
    const t = window.__nadocTest, points = t.getDesignRenderer().getBackboneEntries().map(e => e.pos.toArray())
    const low = [0,1,2].map(i => Math.min(...points.map(p => p[i])))
    const high = [0,1,2].map(i => Math.max(...points.map(p => p[i])))
    const center = low.map((v,i) => (v + high[i]) / 2), span = Math.max(...low.map((v,i) => high[i] - v))
    t.applyCameraPoseForTest({ target: center, position: center.map(v => v + span * 1.3), up: [0,1,0] })
    t.renderViewerFrameForTest()
  })
  if (process.env.NADOC_JJ_REVIEW_DIR) await page.screenshot({ path: path.join(process.env.NADOC_JJ_REVIEW_DIR, 'tether-contacts-on.png') })
  const reversed = await collisionExercise(Number(initialAngle) - 5)
  expect(reversed.angle).toBeLessThan(Number(initialAngle) - .1)
  expect(reversed.worsening).toBeLessThanOrEqual(.0011)
  expect(reversed.displayError).toBeLessThan(1e-4)
  expect(reversed.stretch).toBeLessThanOrEqual(.0011)
  expect(reversed.fixedMoved).toBe(false)
  await restartMove()
  const collisionOff = await collisionExercise(Number(initialAngle) + 5, false)
  expect(collisionOff.worsening).toBeGreaterThan(collisionOn.worsening + .05)
  expect(collisionOff.followers).toHaveLength(6)
  expect(collisionOff.stretch).toBeLessThanOrEqual(.00101)
  console.log('JJ compliant tether motion', JSON.stringify({ collisionOn, reversed, collisionOff }))
  await page.click('#mr-cancel-btn')
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)).toBe(count)
  const restored = await page.evaluate(before => {
    const after = window.__nadocTest.getDesignRenderer().getBackboneEntries()
    return Math.max(...after.map((e,i) => Math.hypot(...e.pos.toArray().map((v,k) => v-before[i][k]))))
  }, displayBefore)
  expect(restored).toBeLessThan(1e-6)
  // Repeat the performance check at the user's latest saved feature position.
  await page.evaluate(async () => {
    const t=window.__nadocTest,api=await import('/src/api/client.js')
    await api.seekFeatures(t.store.getState().currentDesign.feature_log.length-1)
    await t.activateDesignMoveTool(t.store.getState().currentDesign.cluster_transforms.find(c=>c.name==='Geometry Cluster 2').id)
  })
  await page.selectOption('#mr-pivot-sel','ssdna')
  await page.waitForFunction(()=>window.__nadocTest.clusterGizmo.isTetherConstraintActive())
  await page.check('#mr-tether-collisions')
  const currentLive=await exerciseLive()
  console.log('JJ current saved pose live updates',JSON.stringify(currentLive))
  expect(currentLive.max).toBeLessThan(200)
  expect(currentLive.maxAngle).toBeGreaterThan(.001)
  const currentGeometry=await collisionExercise(Number(await page.inputValue('#mr-rx')))
  expect(currentGeometry.worsening).toBeLessThanOrEqual(.0011)
  expect(currentGeometry.stretch).toBeLessThanOrEqual(.0011)
  expect(currentGeometry.displayError).toBeLessThan(1e-4)
  expect(currentGeometry.fixedMoved).toBe(false)
  await page.click('#mr-cancel-btn')
  expect(readFileSync(fixture, 'utf8')).toBe(original)
})

test('JJ_Hinge constrained large rotation Apply', async ({ page }) => {
  test.setTimeout(180000)
  const fixture = path.resolve('../workspace/Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc')
  test.skip(!existsSync(fixture), 'Local user design unavailable')
  const original = readFileSync(fixture, 'utf8')
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.goto('/?doc=__e2e__jj-contact-read-only')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__jj-contact-host')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__jj-contact-host')
  await page.evaluate(async fixture => {
    const t=window.__nadocTest,api=await import('/src/api/client.js')
    t.pauseViewerRenderingForTest();await api.loadDesign(fixture);t.setRepresentation('full')
    await t.activateDesignMoveTool(t.store.getState().currentDesign.cluster_transforms.find(c=>c.name==='Geometry Cluster 2').id)
  },fixture)
  for (const degrees of [55, 65, 90]) {
    await page.selectOption('#mr-pivot-sel', 'ssdna')
    await page.waitForFunction(() => window.__nadocTest.clusterGizmo.isTetherConstraintActive())
    await page.check('#mr-tether-collisions')
    const count = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)
    await page.locator('#mr-rx').fill(String(degrees))
    await page.locator('#mr-rx').press('Tab')
    const acceptedAngle = await page.inputValue('#mr-rx')
    const queued = await page.evaluate(() => window.__nadocTest.clusterGizmo.getAllPendingTransforms())
    expect(queued.length).toBeGreaterThan(1)
    const responsePromise = page.waitForResponse(r => r.url().endsWith('/design/clusters/poses'))
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    const response = await responsePromise
    console.log('JJ Apply', { requested: degrees, field: acceptedAngle, status: response.status() },
      response.status() !== 200 ? await response.text() : '')
    expect(response.status()).toBe(200)
    await page.waitForFunction(count => {
      const t = window.__nadocTest, s = t.store.getState()
      return !s.translateRotateActive && !t.clusterGizmo.getAllPendingTransforms().length
        && s.currentDesign.feature_log.length === count + 1
    }, count)
    expect(await page.evaluate(() => window.__nadocTest.store.getState().lastError)).toBeNull()
    const committed = await page.evaluate(() => {
      const d = window.__nadocTest.store.getState().currentDesign
      return { clusters: d.cluster_transforms, feature: d.feature_log.at(-1) }
    })
    expect(committed.feature.op_kind).toBe('placement-poses')
    for (const pose of queued) {
      const saved = committed.clusters.find(c => c.id === pose.clusterId)
      for (const field of ['translation', 'rotation', 'pivot'])
        pose[field].forEach((value, index) => expect(saved[field][index]).toBeCloseTo(value, 9))
    }
    if (degrees !== 90) await page.evaluate(async () => {
      const t = window.__nadocTest
      await t.activateDesignMoveTool(t.store.getState().currentDesign.cluster_transforms.find(c => c.name === 'Geometry Cluster 2').id)
    })
  }
  // A historical stage is deliberately read-only for this atomic move path.
  // Verify the real rejection is visible, with every pending pose retained.
  await page.evaluate(async () => {
    const t = window.__nadocTest, api = await import('/src/api/client.js')
    await api.seekFeatures(t.store.getState().currentDesign.feature_log.length - 2)
    await t.activateDesignMoveTool(t.store.getState().currentDesign.cluster_transforms.find(c => c.name === 'Geometry Cluster 2').id)
  })
  await page.selectOption('#mr-pivot-sel', 'ssdna')
  await page.check('#mr-tether-collisions')
  await page.locator('#mr-rx').fill('55')
  await page.locator('#mr-rx').press('Tab')
  const pending = await page.evaluate(() => window.__nadocTest.clusterGizmo.getAllPendingTransforms())
  expect(pending.length).toBeGreaterThan(0)
  const refused = page.waitForResponse(r => r.url().endsWith('/design/clusters/poses'))
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  expect((await refused).status()).toBe(409)
  await page.waitForFunction(() => window.__nadocTest.store.getState().translateRotateActive)
  expect(await page.evaluate(() => window.__nadocTest.store.getState().lastError?.message)).toMatch(/latest history/)
  await expect(page.locator('.toast-message').filter({ hasText: 'Return to the latest history' }).last()).toBeVisible()
  expect(await page.evaluate(() => window.__nadocTest.clusterGizmo.getAllPendingTransforms())).toEqual(pending)
  expect(readFileSync(fixture, 'utf8')).toBe(original)
})
