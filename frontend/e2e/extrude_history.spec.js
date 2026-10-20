import { test, expect } from '@playwright/test'
import { withHistoryFixture, withHeldResponse } from './helpers/deformation_history.js'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')
const fields = ['helix_id', 'direction', 'bp_index', 'copy_k', 'strand_id', 'strand_type',
  'domain_index', 'is_five_prime', 'is_three_prime', 'overhang_id', 'placement_source',
  'backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']
function placements(rows) {
  // Keep complete field/value coverage without thousands of Playwright assertion
  // steps blocking its deadline timer on larger native fixtures.
  let missing = 0
  const values = rows.map(row => fields.map(field => {
    if (!Object.hasOwn(row, field)) missing++
    return row[field]
  })).sort((a, b) => JSON.stringify(a.slice(0, 4)).localeCompare(JSON.stringify(b.slice(0, 4))))
  expect(missing, 'Missing native placement fields').toBe(0)
  return values
}

for (const mode of ['Tools', 'fresh-Tools', 'empty-context', 'end-context', 'end-sidebar']) test(`Extrude ${mode} creation Cancel persistence and rollback refusal`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const fresh = mode === 'fresh-Tools'
    if (fresh) await page.evaluate(async () => {
      if (!await (await import('/src/api/client.js')).createDesign('__e2e__fresh-extrude', 'HONEYCOMB')) throw new Error('New part failed')
    })
    const before = await f.checkpoint(), stored = await f.browser()
    const fromEnd = mode.startsWith('end-')
    const panel = page.locator('#extrude-panel')
    const path = fresh ? '/api/design/bundle' : !fromEnd ? '/api/design/bundle-segment' : '/api/design/bundle-deformed-continuation'
    const draft = async () => {
      if (mode === 'Tools' || fresh) {
        await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
        await page.locator('#menu-tools-extrude').click()
      } else if (mode === 'empty-context') {
        await page.locator('#canvas').click({ button: 'right', position: { x: 120, y: 120 } })
        await page.locator('#empty-extrude-btn').click()
      } else {
        await page.evaluate(async () => {
          const { store } = await import('/src/state/store.js')
          store.setState({ toolFilters: { ...store.getState().toolFilters, bluntEnds: true } })
          window.__nadocTest.applyCameraPoseForTest({ position: [18, 16, 35], target: [0, 0, 3] })
        })
        const selected = () => page.evaluate(id => window.__nadocTest.getDomainEndScreenPositions()
          .filter(end => end.openSide === 1 && end.helixId === id).sort((a, b) => b.diskBp - a.diskBp)[0], before.design.helices[0].id)
        await expect.poll(selected).toBeTruthy()
        const end = await selected()
        await page.mouse.click(end.x, end.y, { button: mode === 'end-sidebar' ? 'left' : 'right' })
        await page.locator(mode === 'end-sidebar' ? '#blunt-extrude-btn' : '#blunt-extrude-btn-ctx').click()
      }
      await expect(panel).toBeVisible()
      if (!fromEnd) await page.locator('#extrude-from').selectOption('XZ')
      await page.evaluate(cells => window.SLICE.setSelectedCells(cells), !fromEnd ? [[8, 8]] : [before.design.helices[0].grid_pos])
      await page.locator('#slice-unit').selectOption('bp')
      await page.locator('#slice-length').fill('14')
    }
    await draft()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.locator('#slice-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await draft()
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === path)
    await page.locator('#slice-extrude-btn').click()
    const response = await pending
    expect(response.ok(), await response.text()).toBe(true)
    await expect.poll(async () => (await f.browser()).revision).toBe(before.revision + 1)
    const created = await f.checkpoint(), adopted = await f.browser()
    expect(created.history).toHaveLength(before.history.length + 1)
    expect(created.design.feature_log.at(-1).op_kind).toBe(fresh ? 'bundle-create' : !fromEnd ? 'extrude-segment' : 'extrude-deformed-continuation')
    expect(created.design.feature_log.at(-1).params._proof_version).toBe(1)
    const proof = async () => {
      const result = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(result.ok(), await result.text()).toBe(true)
      expect((await result.json()).status).toBe('verified')
    }
    await proof()
    await expect(panel).not.toBeVisible()
    if (mode === 'end-context' && process.env.NADOC_REVIEW_SCREENSHOT)
      await page.screenshot({ path: process.env.NADOC_REVIEW_SCREENSHOT })
    if (fromEnd) {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const deciding = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0' && r.request().method() === 'DELETE')
      await page.getByTitle('Delete this feature', { exact: true }).first().click()
      const decisionResponse = await deciding
      expect(decisionResponse.ok()).toBe(true)
      const decision = await decisionResponse.json()
      expect(decision.needs_cascade_decision).toBe(true)
      expect(decision.dependents.flatMap(row => row.feature_ids)).toContain(created.design.feature_log.at(-1).id)
      const dialog = page.getByRole('dialog').filter({ hasText: 'Delete dependent features?' })
      await expect(dialog.locator('li')).toHaveText(decision.dependents.map(row => `F${row.index + 1}: ${row.label}`))
      expect(await f.checkpoint()).toEqual(created)
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
      expect(await f.checkpoint()).toEqual(created)
      expect(await f.browser()).toEqual(adopted)
    }
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(placements((await f.browser()).geometry ?? [])).toEqual(placements(stored.geometry ?? []))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(placements((await f.browser()).geometry ?? [])).toEqual(placements(adopted.geometry))
    await proof()
    await page.evaluate(async position => {
      if (!await (await import('/src/api/client.js')).seekFeatures(position)) throw new Error('Seek failed')
    }, fresh ? -2 : 0)
    const rolledBack = await f.checkpoint(), rollbackDisplay = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await expect(page.getByTitle('Return to the latest history position before editing feature inputs.', { exact: true })).toHaveCount(fresh ? 1 : 2)
    const refused = await request.post('http://127.0.0.1:8004' + path, {
      headers: f.headers, data: response.request().postDataJSON(),
    })
    expect(refused.status()).toBe(409)
    expect((await refused.json()).detail.code).toBe('historical_cursor')
    expect(await f.checkpoint()).toEqual(rolledBack)
    expect(await f.browser()).toEqual(rollbackDisplay)
  }, 'extrude-blocked')
})

test('Bundle Extrude history Cancel Save and Bend Sweep replay persistence', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const modal = page.getByRole('dialog', { name: 'Edit Bundle', exact: true })
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      await page.getByTitle('Edit Native bounded bundle parameters', { exact: true }).click()
      await expect(modal).toBeVisible()
    }
    const proof = async () => {
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(response.ok()).toBe(true)
      expect((await response.json()).status).toBe('verified')
    }
    expect(before.redo).toHaveLength(1)
    expect(before.design.feature_log[0].evicted).toBe(true)
    await proof()
    await open()
    await modal.getByLabel('Length (bp)', { exact: true }).fill('48')
    await modal.getByLabel('Name', { exact: true }).fill('Cancelled Bundle')
    await modal.getByRole('button', { name: 'Add cell', exact: true }).click()
    await modal.getByLabel('Cell 2 column', { exact: true }).fill('1')
    await modal.getByLabel('Remove cell 2', { exact: true }).click()
    await modal.getByLabel('Plane', { exact: true }).selectOption('XZ')
    await modal.getByLabel('Lattice', { exact: true }).selectOption('SQUARE')
    await modal.getByLabel('Strands', { exact: true }).selectOption('scaffold')
    await modal.getByLabel('Ligate adjacent ends', { exact: true }).uncheck()
    await modal.getByLabel('Separate fresh extrusions', { exact: true }).uncheck()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(modal).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await open()
    await expect(modal.getByLabel('Length (bp)', { exact: true })).toHaveValue('42')
    await expect(modal.getByLabel('Plane', { exact: true })).toHaveValue('XY')
    await expect(modal.getByLabel('Lattice', { exact: true })).toHaveValue('HONEYCOMB')
    await expect(modal.getByLabel('Strands', { exact: true })).toHaveValue('both')
    await modal.getByLabel('Length (bp)', { exact: true }).fill('48')
    await modal.getByLabel('Name', { exact: true }).fill('Edited native Bundle')
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0/edit')
    await modal.getByRole('button', { name: 'Save', exact: true }).click()
    const response = await pending
    expect(response.ok(), await response.text()).toBe(true)
    await expect(modal).not.toBeVisible()
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(after.design.feature_log[0].params).toMatchObject({ length_bp: 48, name: 'Edited native Bundle' })
    expect(after.design.feature_log[1].op_snapshot).toEqual(before.design.feature_log[1].op_snapshot)
    expect(after.design.feature_log[2].params).toEqual(before.design.feature_log[2].params)
    expect(after.design.feature_log.map(r => r.id)).toEqual(before.design.feature_log.map(r => r.id))
    expect(after.design.helices.map(h => h.id)).toEqual(before.design.helices.map(h => h.id))
    expect(placements(adopted.geometry)).not.toEqual(placements(stored.geometry))
    const geometry = await page.evaluate(async () => {
      const { _request } = await import('/src/api/client.js')
      return _request('GET', '/design/geometry')
    })
    expect(geometry?.nucleotides).toBeTruthy()
    expect(placements(adopted.geometry)).toEqual(placements(geometry.nucleotides))
    await proof()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(placements((await f.browser()).geometry)).toEqual(placements(stored.geometry))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(placements((await f.browser()).geometry)).toEqual(placements(adopted.geometry))
    await proof()
    await open()
    await expect(modal.getByLabel('Length (bp)', { exact: true })).toHaveValue('48')
    await expect(modal.getByLabel('Name', { exact: true })).toHaveValue('Edited native Bundle')
    await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(modal).not.toBeVisible()
  }, 'extrude-chain')
})

const families = [
  ['extrude-segment', 'Extrude Segment'],
  ['extrude-continuation', 'Continuation'],
  ['extrude-deformed-continuation', 'Deformed Continuation'],
  ['extrude-frame', 'Frame Extrusion'],
  ['circle-segment', 'Circle Segment'],
  ['overhang-extrude', 'Overhang Extrusion'],
]
for (const [kind, title] of families) test('Extrude matrix ' + kind + ' controls Cancel Save persistence', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const modal = page.getByRole('dialog', { name: 'Edit ' + title, exact: true })
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      await page.getByTitle('Edit ' + kind + ' parameters', { exact: true }).first().click()
      await expect(modal).toBeVisible()
    }
    const patch = kind === 'circle-segment' ? { cell_lengths: [14] } : { length_bp: 14 }
    const draft = async () => {
      await modal.getByLabel(kind === 'circle-segment' ? 'Cell 1 length (bp)' : 'Length (bp)', { exact: true }).fill('14')
      if (kind !== 'overhang-extrude') {
        await modal.getByLabel('Cell 1 column', { exact: true }).fill('5')
        await modal.getByLabel('Separate fresh extrusions', { exact: true }).uncheck()
        Object.assign(patch, { cells: [[4, 5]], separate_fresh_extrusions: false })
      }
      if (['extrude-segment', 'extrude-continuation', 'circle-segment'].includes(kind)) {
        await modal.getByLabel('Offset (nm)', { exact: true }).fill('1.5')
        await modal.getByLabel('Strands', { exact: true }).selectOption('staples')
        await modal.getByLabel('Ligate adjacent ends', { exact: true }).uncheck()
        Object.assign(patch, { offset_nm: 1.5, strand_filter: 'staples', ligate_adjacent: false })
      }
      if (kind === 'extrude-continuation') {
        const id = before.design.lattice_frames[0].id
        await modal.getByLabel('Source frame ID', { exact: true }).fill(id)
        await modal.getByLabel('Extend existing helix in place', { exact: true }).uncheck()
        Object.assign(patch, { source_frame_id: id, extend_inplace: false })
      }
      if (kind === 'extrude-deformed-continuation') {
        const id = before.design.helices[0].id
        await modal.getByLabel('Frame definition', { exact: true }).selectOption('derived')
        await modal.getByLabel('Reference helix ID', { exact: true }).fill(id)
        await modal.getByLabel('Source bp', { exact: true }).fill('10')
        Object.assign(patch, { ref_helix_id: id, source_bp: 10 })
      }
      if (kind === 'extrude-frame') {
        await modal.getByLabel('Frame source', { exact: true }).selectOption('independent')
        await modal.getByLabel('Name', { exact: true }).fill('Edited Frame')
        for (const [axis, value] of [['X', '3'], ['Y', '2'], ['Z', '1']])
          await modal.getByLabel('Translation ' + axis + ' (nm)', { exact: true }).fill(value)
        Object.assign(patch, { name: 'Edited Frame', translation_nm: [3, 2, 1],
          rotation_xyzw: [0, 0, 0, 1], source_frame_id: null, source_legacy_plane: false })
      }
      if (kind === 'overhang-extrude') {
        await modal.getByLabel('Reuse existing helix', { exact: true }).uncheck()
        patch.reuse_existing_helix = false
      }
    }
    const proof = async () => {
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(response.ok()).toBe(true)
      expect((await response.json()).status).toBe('verified')
    }
    expect(before.redo).toHaveLength(1)
    expect(before.design.feature_log[1].evicted).toBe(true)
    await proof()
    await open(); await draft()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(modal).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await open(); await draft()
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/1/edit')
    await modal.getByRole('button', { name: 'Save', exact: true }).click()
    const response = await pending
    expect(response.ok(), await response.text()).toBe(true)
    await expect(modal).not.toBeVisible()
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(after.design.feature_log[1].params).toMatchObject(patch)
    expect(after.design.feature_log.at(-1).params).toEqual(before.design.feature_log.at(-1).params)
    expect(after.design.feature_log.map(r => r.id)).toEqual(before.design.feature_log.map(r => r.id))
    expect(placements(adopted.geometry)).not.toEqual(placements(stored.geometry))
    const geometry = await page.evaluate(async () => {
      const { _request } = await import('/src/api/client.js')
      return _request('GET', '/design/geometry')
    })
    expect(geometry?.nucleotides).toBeTruthy()
    expect(placements(adopted.geometry)).toEqual(placements(geometry.nucleotides))
    await proof()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(placements((await f.browser()).geometry)).toEqual(placements(stored.geometry))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(placements((await f.browser()).geometry)).toEqual(placements(adopted.geometry))
    await proof()
    await open()
    await expect(modal.getByLabel(kind === 'circle-segment' ? 'Cell 1 length (bp)' : 'Length (bp)', { exact: true })).toHaveValue('14')
    await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(modal).not.toBeVisible()
  }, kind)
})


test('Extrude dependency view identifies its downstream routing child without mutation', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/dependencies')
    await page.getByTitle('View F1 dependencies', { exact: true }).click()
    const response = await pending
    expect(response.ok(), await response.text()).toBe(true)
    const graph = await response.json()
    expect(graph.design_id).toBe(before.design.id)
    expect(graph.revision).toBe(before.revision)
    const modal = page.getByRole('dialog', { name: 'F1 dependencies', exact: true })
    await expect(modal.getByLabel('Parents', { exact: true })).toContainText('None')
    await expect(modal.getByLabel('Dependents', { exact: true })).toContainText('F2: Output nick pair')
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await modal.getByRole('button', { name: 'Close', exact: true }).last().click()
    await expect(modal).not.toBeVisible()
    await page.getByTitle('View F2 dependencies', { exact: true }).click()
    const routing = page.getByRole('dialog', { name: 'F2 dependencies', exact: true })
    await expect(routing.getByLabel('Parents', { exact: true })).toContainText('F1:')
    await expect(routing.getByLabel('Dependents', { exact: true })).toContainText('None')
    await routing.getByRole('button', { name: 'Close', exact: true }).last().click()
    await expect(routing).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
  }, 'extrude-nick-batch')
})

test('Extrude late Save response cannot replace a reopened same-ID part', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Edit extrude-frame parameters', { exact: true }).click()
    const modal = page.getByRole('dialog', { name: 'Edit Frame Extrusion', exact: true })
    await modal.getByLabel('Length (bp)', { exact: true }).fill('16')
    await page.evaluate(() => {
      window.__extrudeReplyFinished = false
      const listener = event => {
        if (event.detail.path === '/design/features/0/edit'
            && ['complete', 'aborted', 'error'].includes(event.detail.phase)) {
          window.__extrudeReplyFinished = true
          window.removeEventListener('nadoc:api-request', listener)
        }
      }
      window.addEventListener('nadoc:api-request', listener)
    })
    await withHeldResponse(page, '/api/design/features/0/edit', async ({ ready, release }) => {
      await modal.getByRole('button', { name: 'Save', exact: true }).click()
      const committed = await ready
      expect(committed.response.ok()).toBe(true)
      expect((await f.checkpoint()).revision).toBe(before.revision + 1)
      expect(await f.browser()).toEqual(stored)
      await page.evaluate(async file => {
        if (!await (await import('/src/api/client.js')).loadDesign(file)) throw new Error('Reopen failed')
      }, f.file)
      await expect(modal).not.toBeVisible()
      const reopened = await f.checkpoint(), current = await f.browser()
      expect(reopened.design.id).toBe(before.design.id)
      expect(reopened.design.feature_log[0].params.length_bp).toBe(14)
      await release()
      // Drain the real client response handler, not only the routed HTTP reply.
      await expect.poll(() => page.evaluate(() => window.__extrudeReplyFinished)).toBe(true)
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      expect(await f.checkpoint()).toEqual(reopened)
      expect(await f.browser()).toEqual(current)
      await expect(page.locator('[data-history-status]')).toHaveCount(0)
    })
  }, 'extrude-nick-batch')
})

test('Extrude representative 18-helix history Save and Cancel latency', async ({ page, request }) => {
  test.setTimeout(180_000)
  await page.addInitScript(() => {
    const timer = setInterval(() => {
      if (window.__nadocTest?.pauseViewerRenderingForTest) {
        window.__nadocTest.pauseViewerRenderingForTest(); clearInterval(timer)
      }
    }, 20)
  })
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    expect(before.design.helices).toHaveLength(18)
    expect(before.design.helices.every(helix => helix.length_bp === 504)).toBe(true)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const modal = page.getByRole('dialog', { name: 'Edit Frame Extrusion', exact: true })
    const opening = performance.now()
    await page.getByTitle('Edit extrude-frame parameters', { exact: true }).click()
    await expect(modal).toBeVisible()
    const openMs = performance.now() - opening
    await modal.getByLabel('Length (bp)', { exact: true }).fill('506')
    const cancelling = performance.now()
    await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(modal).not.toBeVisible()
    const cancelMs = performance.now() - cancelling
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.getByTitle('Edit extrude-frame parameters', { exact: true }).click()
    await modal.getByLabel('Length (bp)', { exact: true }).fill('506')
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0/edit')
    const publishing = performance.now()
    await modal.getByRole('button', { name: 'Save', exact: true }).click()
    const response = await pending
    if (!response.ok()) throw new Error('Large Extrude edit refused: ' + await response.text())
    await expect(modal).not.toBeVisible()
    const applyMs = performance.now() - publishing
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.design.helices.every(helix => helix.length_bp === 506)).toBe(true)
    expect(adopted.design.feature_log[0].params.length_bp).toBe(506)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
    console.log(JSON.stringify({ metric: 'extrude-history-18x504', openMs, applyMs, cancelMs,
      sourceBytes: JSON.stringify(before.design).length, nucleotideRows: adopted.geometry.length, gpuRasterExcluded: true }))
    expect(applyMs).toBeLessThanOrEqual(20_000)
    expect(cancelMs).toBeLessThanOrEqual(400)
  }, 'extrude-large')
})

for (const finish of ['Cancel', 'Save retry']) test(`Extrude refuses partial routing targets and names the failing child (${finish})`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Expand Fine Routing', { exact: true }).click()
    await page.getByTitle('Edit extrude-frame parameters', { exact: true }).click()
    const modal = page.getByRole('dialog', { name: 'Edit Frame Extrusion', exact: true })
    await expect(modal).toBeVisible()
    await modal.getByLabel('Length (bp)', { exact: true }).fill('5')
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0/edit')
    await modal.getByRole('button', { name: 'Save', exact: true }).click()
    const response = await pending
    expect(response.status()).toBe(409)
    const failure = (await response.json()).detail
    expect(failure.feature_id).toBe(before.design.feature_log[1].children[0].id)
    await expect(modal.getByRole('alert')).toContainText('Output nick pair cannot regenerate after this edit:')
    await expect(page.locator('[data-fl-row="2.0"] [data-history-status="error"]')).toHaveText('Edit failed')
    await expect(page.locator('[data-fl-row="2.1"] [data-history-status="blocked"]')).toHaveText('Blocked')
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await expect(modal.getByLabel('Length (bp)', { exact: true })).toHaveValue('5')
    let elapsedMs
    if (finish === 'Save retry') {
      await modal.getByLabel('Length (bp)', { exact: true }).fill('16')
      const retry = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0/edit')
      const started = performance.now()
      await modal.getByRole('button', { name: 'Save', exact: true }).click()
      const saved = await retry
      expect(saved.ok(), await saved.text()).toBe(true)
      await expect(modal).not.toBeVisible()
      elapsedMs = performance.now() - started
      const after = await f.checkpoint()
      expect(after.revision).toBe(before.revision + 1)
      expect(after.history).toHaveLength(before.history.length + 1)
      expect(after.design.feature_log[1].children.map(row => row.id)).toEqual(before.design.feature_log[1].children.map(row => row.id))
      const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(proof.ok()).toBe(true)
      expect((await proof.json()).status).toBe('verified')
    } else {
      const started = performance.now()
      await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(modal).not.toBeVisible()
      elapsedMs = performance.now() - started
    }
    await expect(modal).not.toBeVisible()
    await expect(page.locator('[data-history-status]')).toHaveCount(0)
    if (finish === 'Cancel') expect(await f.checkpoint()).toEqual(before)
    console.log(JSON.stringify({ metric: 'extrude-history-small', action: finish, elapsedMs }))
    expect(elapsedMs).toBeLessThanOrEqual(finish === 'Cancel' ? 400 : 6000)
    return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 409 (Conflict)'] }
  }, 'extrude-blocked')
})
