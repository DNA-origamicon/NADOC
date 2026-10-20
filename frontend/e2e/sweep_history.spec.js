import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')
const endpoint = '/api/design/features/sweep-preview'

for (const mode of ['independent', 'attached-end', 'context-end']) test(`Sweep ${mode} creation Cancel history edit and persistence`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const panel = page.locator('#sweep-panel')
    const responseFor = path => page.waitForResponse(r => new URL(r.url()).pathname === path)
    const proof = async () => {
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(response.ok(), await response.text()).toBe(true)
      expect((await response.json()).status).toBe('verified')
    }
    const createDraft = async () => {
      const preview = responseFor('/api/design/sweep/preview')
      if (mode === 'context-end') {
        await page.evaluate(async () => {
          const { store } = await import('/src/state/store.js')
          store.setState({ toolFilters: { ...store.getState().toolFilters, bluntEnds: true } })
          window.__nadocTest.applyCameraPoseForTest({ position: [18, 16, 35], target: [0, 0, 7] })
        })
        const selected = () => page.evaluate(id => window.__nadocTest.getDomainEndScreenPositions()
          .find(end => end.openSide === 1 && end.helixId === id), before.design.helices[0].id)
        await expect.poll(selected).toBeTruthy()
        const end = await selected()
        await page.mouse.click(end.x, end.y, { button: 'right' })
        await page.locator('#blunt-sweep-btn-ctx').click()
      } else {
        await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
        await page.locator('#menu-tools-sweep').click()
      }
      await expect(panel).toBeVisible()
      if (mode === 'independent') {
        await page.locator('#sweep-plane').selectOption('XZ')
        await page.evaluate(() => window.SLICE.setSelectedCells([[8, 8]]))
      } else if (mode === 'attached-end') await page.locator('#sweep-source').selectOption('1')
      expect((await preview).ok()).toBe(true)
      await expect(page.locator('#sweep-apply')).toBeEnabled()
      await page.locator('#sweep-apply').click()
      await expect(page.locator('#sweep-step')).toContainText('2/2')
      await expect(page.locator('#sweep-apply')).toBeEnabled()
    }
    await proof()
    await createDraft()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.locator('#sweep-cancel').click()
    await page.locator('#sweep-cancel').click()
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await createDraft()
    const publishing = responseFor('/api/design/sweep')
    await page.locator('#sweep-apply').click()
    const response = await publishing
    expect(response.ok(), await response.text()).toBe(true)
    await expect(panel).not.toBeVisible()
    const created = await f.checkpoint(), feature = created.design.feature_log.at(-1)
    expect(created.revision).toBe(before.revision + 1)
    expect(created.history).toHaveLength(before.history.length + 1)
    expect(created.redo).toHaveLength(0)
    expect(feature.op_kind).toBe('sweep')
    expect(feature.params._proof_version).toBe(1)
    expect(feature.params.source_helix_id).toBe(mode === 'independent' ? null : before.design.helices[0].id)
    await proof()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const preparing = responseFor(endpoint)
    await page.locator('#fl-list [title^="Edit sweep path"]').click()
    expect((await preparing).ok()).toBe(true)
    const axis = mode === 'independent' ? 'Y' : 'Z'
    const evaluating = responseFor(endpoint + '/evaluate')
    await page.getByLabel(`Point ${axis} (nm)`, { exact: true }).fill('12')
    expect((await evaluating).ok()).toBe(true)
    await expect(page.locator('#sweep-apply')).toBeEnabled()
    const applying = responseFor(endpoint + '/apply')
    await page.locator('#sweep-apply').click()
    expect((await applying).ok()).toBe(true)
    await expect(panel).not.toBeVisible()
    const edited = await f.checkpoint()
    expect(edited.design.feature_log.at(-1).id).toBe(feature.id)
    expect(edited.revision).toBe(created.revision + 1)
    await proof()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.checkpoint()).design.feature_log.at(-1).params).toEqual(feature.params)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.checkpoint()).design.feature_log.at(-1).params).toEqual(edited.design.feature_log.at(-1).params)
    await proof()
  })
})

test('Sweep lists upstream dependents and refuses history edits at rollback', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const decisionResponse = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0'
      && r.request().method() === 'DELETE')
    await page.locator('[title="Delete this feature"]').first().click()
    const response = await decisionResponse
    expect(response.ok()).toBe(true)
    const decision = await response.json()
    expect(decision.needs_cascade_decision).toBe(true)
    expect(decision.dependents.flatMap(row => row.feature_ids)).toEqual(['selected-sweep'])
    const dialog = page.getByRole('dialog').filter({ hasText: 'Delete dependent features?' })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('li')).toHaveText(decision.dependents.map(row => `F${row.index + 1}: ${row.label}`))
    expect(await f.checkpoint()).toEqual(before)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.evaluate(async () => {
      if (!await (await import('/src/api/client.js')).seekFeatures(1)) throw new Error('Seek failed')
    })
    const rolledBack = await f.checkpoint(), writes = f.writes.length
    await expect(page.locator('[title="Return to the latest history position before editing feature inputs."]').first()).toBeDisabled()
    expect(await f.checkpoint()).toEqual(rolledBack)
    expect(f.writes).toHaveLength(writes)
    await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
    await page.locator('#menu-tools-sweep').click()
    await expect(page.locator('#sweep-panel')).not.toBeVisible()
    await expect(page.locator('.toast-message').filter({ hasText: 'Return to the latest history position before creating a Sweep.' })).toBeVisible()
    expect(await f.checkpoint()).toEqual(rolledBack)
    expect(f.writes).toHaveLength(writes)
    await page.evaluate(async () => {
      if (!await (await import('/src/api/client.js')).seekFeatures(-1)) throw new Error('Return to tip failed')
    })
    await expect(page.locator('#fl-list [title^="Edit sweep path"]')).toBeEnabled()
  }, 'sweep-extrude')
})

for (const [variant, length, outcome] of [
  ['sweep-nick', 12, 'regenerates'], ['sweep-nick', 1, 'removes empty targets'],
  ['sweep-nick-batch', 1, 'refuses partial targets'],
]) test(`Sweep downstream routing ${outcome}`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const panel = page.locator('#sweep-panel')
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const preparing = page.waitForResponse(r => new URL(r.url()).pathname === endpoint)
    await page.locator('#fl-list [title^="Edit sweep path"]').click()
    expect((await preparing).ok()).toBe(true)
    await expect(panel).toBeVisible()
    const evaluating = page.waitForResponse(r => new URL(r.url()).pathname === endpoint + '/evaluate')
    await page.getByLabel('Point Z (nm)', { exact: true }).fill(String(length))
    expect((await evaluating).ok()).toBe(true)
    await expect(page.locator('#sweep-apply')).toBeEnabled()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    const applying = page.waitForResponse(r => new URL(r.url()).pathname === endpoint + '/apply')
    await page.locator('#sweep-apply').click()
    const response = await applying
    if (outcome === 'refuses partial targets') {
      expect(response.status()).toBe(409)
      expect((await response.json()).detail.feature_id).toBe('later-nick')
      await expect(panel).toContainText('Nick on second Sweep cell cannot regenerate')
      await expect(page.locator('[data-history-status="error"]')).toHaveCount(1)
      expect(await f.checkpoint()).toEqual(before)
      expect(await f.browser()).toEqual(stored)
      await page.locator('#sweep-cancel').click()
      const cancelled = page.waitForResponse(r => new URL(r.url()).pathname === endpoint + '/cancel')
      await page.locator('#sweep-cancel').click()
      expect((await cancelled).ok()).toBe(true)
      await expect(page.locator('[data-history-status]')).toHaveCount(0)
      expect(await f.checkpoint()).toEqual(before)
      return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 409 (Conflict)'] }
    }
    expect(response.ok(), await response.text()).toBe(true)
    await expect(panel).not.toBeVisible()
    if (outcome === 'removes empty targets') {
      await expect(page.locator('.toast-message').filter({ hasText: 'Removed 1 fine-routing feature' })).toBeVisible()
    }
    const after = await f.checkpoint()
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    const children = after.design.feature_log.flatMap(row => row.children ?? [])
    expect(children.some(child => child.id === 'later-nick')).toBe(outcome === 'regenerates')
    const prove = async () => {
      const r = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(r.ok()).toBe(true)
      const proof = await r.json()
      expect(proof.status).toBe('verified')
      expect(proof.cold_replay.authoring_equal).toBe(true)
      expect(proof.cold_replay.geometry_equal).toBe(true)
      expect(placements((await f.browser()).geometry)).toEqual(placements(proof.cold_replay.geometry))
    }
    await prove()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(placements((await f.browser()).geometry)).toEqual(placements(stored.geometry))
    expect((await f.checkpoint()).design.feature_log.flatMap(row => row.children ?? []).some(c => c.id === 'later-nick')).toBe(true)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    await prove()
  }, variant)
})

const fields = ['helix_id', 'direction', 'bp_index', 'copy_k', 'strand_id', 'strand_type',
  'domain_index', 'is_five_prime', 'is_three_prime', 'overhang_id', 'placement_source',
  'backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']
function placements(rows) {
  let missing = 0
  const values = rows.map(row => fields.map(field => {
    if (!Object.hasOwn(row, field)) missing++
    return row[field]
  })).sort((a, b) => JSON.stringify(a.slice(0, 4)).localeCompare(JSON.stringify(b.slice(0, 4))))
  expect(missing, 'Missing native placement fields').toBe(0)
  return values
}

test('attached Sweep history controls Cancel Apply and downstream Extrude persistence', async ({ page, request }) => {
  if (process.env.NADOC_REVIEW_SCREENSHOT) await page.setViewportSize({ width: 1920, height: 1080 })
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const panel = page.locator('#sweep-panel')
    const waitResponse = path => page.waitForResponse(r => new URL(r.url()).pathname === path)
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const pending = waitResponse(endpoint)
      await page.locator('#fl-list [title^="Edit sweep path"]').click()
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      await expect(panel).toBeVisible()
      await expect(page.locator('#sweep-apply')).toHaveText('Apply')
    }
    const change = async action => {
      const pending = waitResponse(endpoint + '/evaluate')
      await action()
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      await expect(page.locator('#sweep-apply')).toBeEnabled()
      return response.request().postDataJSON().params
    }
    const proof = async () => {
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(response.ok()).toBe(true)
      expect((await response.json()).status).toBe('verified')
    }
    expect(before.redo).toHaveLength(1)
    await proof()
    await open()
    if (process.env.NADOC_REVIEW_SCREENSHOT) await page.screenshot({ path: process.env.NADOC_REVIEW_SCREENSHOT })
    await change(() => page.getByLabel('Point Z (nm)', { exact: true }).fill('6'))
    await change(() => page.getByLabel('Add sweep point', { exact: true }).click())
    await expect(panel.getByRole('option')).toHaveCount(3)
    await change(() => page.getByLabel('Delete point 2', { exact: true }).click())
    await expect(panel.getByRole('option')).toHaveCount(2)
    await change(() => page.getByLabel('Control point orientation', { exact: true }).check())
    await change(async () => {
      await page.getByLabel('Twist (degrees)', { exact: true }).fill('10')
      await page.getByLabel('Twist (degrees)', { exact: true }).press('Tab')
    })
    await change(() => page.getByLabel('Control point orientation', { exact: true }).uncheck())
    await page.locator('#sweep-cancel').click() // Previous retains the private draft.
    await expect(page.locator('#sweep-apply')).toHaveText('Next')
    await page.locator('#sweep-apply').click()
    await expect(page.getByLabel('Point Z (nm)', { exact: true })).toHaveValue('6')
    await expect(page.getByLabel('Control point orientation', { exact: true })).not.toBeChecked()
    await change(() => page.locator('#sweep-visual').uncheck())
    await change(() => page.locator('#sweep-visual').check())
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.locator('#sweep-cancel').click() // Previous
    const cancelled = waitResponse(endpoint + '/cancel')
    await page.locator('#sweep-cancel').click() // Cancel
    expect((await cancelled).ok()).toBe(true)
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    await open()
    const inputs = await change(() => page.getByLabel('Point Z (nm)', { exact: true }).fill('6'))
    const applied = waitResponse(endpoint + '/apply')
    await page.locator('#sweep-apply').click()
    expect((await applied).ok()).toBe(true)
    await expect(panel).not.toBeVisible()
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(after.design.feature_log.map(e => e.id)).toEqual(before.design.feature_log.map(e => e.id))
    expect(after.design.feature_log.at(-1).params).toEqual(before.design.feature_log.at(-1).params)
    expect(after.design.feature_log.find(e => e.id === 'selected-sweep').params.points_nm).toEqual(inputs.points_nm)
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
    await expect(page.getByLabel('Point Z (nm)', { exact: true })).toHaveValue('6')
    await page.locator('#sweep-cancel').click()
    const closed = waitResponse(endpoint + '/cancel')
    await page.locator('#sweep-cancel').click()
    expect((await closed).ok()).toBe(true)
    await expect(panel).not.toBeVisible()
  }, 'sweep-extrude')
})

for (const mode of ['independent', 'start', 'detached']) {
test(mode + ' Sweep source matrix Cancel Apply and downstream persistence', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const panel = page.locator('#sweep-panel')
    const waitResponse = path => page.waitForResponse(r => new URL(r.url()).pathname === path)
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const pending = waitResponse(endpoint)
      await page.locator('#fl-list [title^="Edit sweep path"]').click()
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      await expect(panel).toBeVisible()
      await expect(page.locator('#sweep-apply')).toHaveText('Apply')
    }
    const change = async (action, matches = () => true) => {
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === endpoint + '/evaluate'
        && matches(r.request().postDataJSON().params))
      await action()
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      await expect(page.locator('#sweep-apply')).toBeEnabled()
      return response.request().postDataJSON().params
    }
    const proof = async () => {
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(response.ok()).toBe(true)
      expect((await response.json()).status).toBe('verified')
    }
    expect(before.redo).toHaveLength(1)
    await proof()
    const draft = async () => {
      await change(() => page.locator('#sweep-cancel').click())
      await expect(page.locator('#sweep-source option')).toHaveCount(5)
      await expect(page.locator('#sweep-source')).toHaveValue(mode === 'independent' ? '' : mode === 'start' ? '0' : '1')
      expect(await page.locator('#sweep-source').textContent()).not.toContain('(8, 8)')
      await expect(page.locator('#sweep-plane')).toHaveValue('XY')
      if (mode === 'independent') await expect(page.locator('#sweep-plane')).toBeEnabled()
      else await expect(page.locator('#sweep-plane')).toBeDisabled()
      await change(() => page.locator('#sweep-ligate').check())
      await change(() => page.locator('#sweep-ligate').uncheck())
      await change(() => page.locator('#sweep-apply').click())
      await page.locator('.sweep-point').first().click()
      const orient = page.getByLabel('Control point orientation', { exact: true })
      if (mode !== 'independent') await expect(orient).toBeDisabled()
      else await expect(orient).toBeEnabled()
      if (mode === 'detached') {
        const moved = await change(() => page.getByLabel('Point X (nm)', { exact: true }).fill('1'), p => p.points_nm[0][0] === 1)
        expect(moved.detach_source).toBe(true)
        const returned = await change(() => page.getByLabel('Point X (nm)', { exact: true }).fill('0'), p => p.points_nm[0][0] === 0)
        expect(returned.detach_source).toBe(true)
        await expect(orient).toBeEnabled()
      }
      await page.locator('.sweep-point').last().click()
      await change(() => page.getByLabel('Point Z (nm)', { exact: true }).fill(mode === 'start' ? '-6' : '6'))
      await change(() => orient.check())
      for (const [label, value] of [['Tilt X', '0'], ['Tilt Y', '0'], ['Twist', '10']]) {
        const input = page.getByLabel(label + ' (degrees)', { exact: true })
        if (await input.inputValue() !== value) await change(async () => {
          await input.fill(value); await input.press('Tab')
        })
      }
    }
    await open()
    await draft()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.locator('#sweep-cancel').click() // Previous
    const cancelled = waitResponse(endpoint + '/cancel')
    await page.locator('#sweep-cancel').click() // Cancel
    expect((await cancelled).ok()).toBe(true)
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    await open()
    await draft()
    const applied = waitResponse(endpoint + '/apply')
    await page.locator('#sweep-apply').click()
    expect((await applied).ok()).toBe(true)
    await expect(panel).not.toBeVisible()
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(after.design.feature_log.map(e => e.id)).toEqual(before.design.feature_log.map(e => e.id))
    expect(after.design.feature_log.at(-1).params).toEqual(before.design.feature_log.at(-1).params)
    const selected = after.design.feature_log.find(e => e.id === 'selected-sweep').params
    const original = before.design.feature_log.find(e => e.id === 'selected-sweep').params
    expect(selected.source_helix_id).toBe(original.source_helix_id)
    expect(selected.source_end).toBe(mode === 'start' ? 'start' : 'end')
    expect(selected.detach_source).toBe(mode === 'detached')
    expect(selected.cells).toEqual(original.cells)
    expect(selected.points_nm).toEqual([[0, 0, 0], [0, 0, mode === 'start' ? -6 : 6]])
    expect(selected.orientations_deg).toEqual([null, [0, 0, 10]])
    expect(selected).toEqual({ ...original, points_nm: [[0, 0, 0], [0, 0, mode === 'start' ? -6 : 6]],
      orientations_deg: [null, [0, 0, 10]], detach_source: mode === 'detached' })
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
    await expect(page.getByLabel('Point Z (nm)', { exact: true })).toHaveValue(mode === 'start' ? '-6' : '6')
    await expect(page.getByLabel('Twist (degrees)', { exact: true })).toHaveValue('10')
    await page.locator('.sweep-point').first().click()
    if (mode === 'start') await expect(page.getByLabel('Control point orientation', { exact: true })).toBeDisabled()
    else await expect(page.getByLabel('Control point orientation', { exact: true })).toBeEnabled()
    await page.locator('#sweep-cancel').click()
    const closed = waitResponse(endpoint + '/cancel')
    await page.locator('#sweep-cancel').click()
    expect((await closed).ok()).toBe(true)
    await expect(panel).not.toBeVisible()
  }, 'sweep-' + mode)
})
}


for (const large of [false, true]) test(`Sweep representative ${large ? '18-helix' : 'small'} preview Apply and Cancel latency`, async ({ page, request }) => {
  test.setTimeout(240_000)
  await page.addInitScript(() => {
    const timer = setInterval(() => {
      if (window.__nadocTest?.pauseViewerRenderingForTest) {
        window.__nadocTest.pauseViewerRenderingForTest(); clearInterval(timer)
      }
    }, 20)
  })
  await withHistoryFixture({ page, request }, 'bend', async f => {
    await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const open = async () => {
      const prepared = page.waitForResponse(r => new URL(r.url()).pathname === endpoint, { timeout: 60_000 })
      await page.locator('#fl-list [title^="Edit sweep path"]').click()
      const response = await prepared
      if (!response.ok()) throw new Error('Sweep preparation refused: ' + await response.text())
      expect((await response.json()).candidate).toBeNull()
      try { await expect(page.locator('#sweep-panel')).toBeVisible({ timeout: 15_000 }) }
      catch (error) { throw new Error(error.message + '\nSweep diagnostics: ' + (await page.locator('.toast-message').allTextContents()).join('; ')) }
      await expect(page.locator('#sweep-apply')).toBeEnabled({ timeout: 15_000 })
    }
    await open()
    const prefixRoots = await page.evaluate(() => window.__nadocTest.scene.children
      .filter(n => n.name === 'privateDeformationPreview').map(n => n.uuid))
    expect(prefixRoots).toHaveLength(1)
    await page.evaluate(() => {
      window.__sweepEvaluateTimings = []
      window.addEventListener('nadoc:api-request', event => {
        if (event.detail.path === '/design/features/sweep-preview/evaluate' && event.detail.phase === 'complete')
          window.__sweepEvaluateTimings.push(event.detail)
      })
    })
    const samples = []
    const profiler = process.env.NADOC_SWEEP_PROFILE ? await page.context().newCDPSession(page) : null
    if (profiler) { await profiler.send('Profiler.enable'); await profiler.send('Profiler.start') }
    for (const z of Array.from({ length: 12 }, (_, i) => (large ? 172 : 12) + i)) {
      samples.push(await page.evaluate(async value => {
        // Native guide update completes before the resulting extent is shown.
        // A Sweep edit intentionally never rebuilds a full nucleotide layer.
        const extent = () => document.querySelector('#sweep-total-bp').textContent
        const before = extent(), input = document.querySelector('[aria-label="Point Z (nm)"]')
        const start = performance.now()
        input.value = String(value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
        input.dispatchEvent(new Event('change', { bubbles: true }))
        await new Promise((resolve, reject) => {
          const tick = () => extent() !== before && /^\d/.test(extent()) && !document.querySelector('#sweep-apply').disabled ? resolve()
            : performance.now() - start > 20_000 ? reject(new Error('Sweep preview did not update')) : setTimeout(tick, 4)
          tick()
        })
        return performance.now() - start
      }, z))
    }
    expect(await page.evaluate(() => window.__nadocTest.scene.children
      .filter(n => n.name === 'privateDeformationPreview').map(n => n.uuid))).toEqual(prefixRoots)
    if (profiler) {
      const { profile } = await profiler.send('Profiler.stop')
      const nodes = new Map(profile.nodes.map(node => [node.id, node.callFrame]))
      const totals = new Map()
      for (let i = 0; i < profile.samples.length; i++) {
        const frame = nodes.get(profile.samples[i])
        const name = `${frame.functionName} ${frame.url}:${frame.lineNumber + 1}`
        totals.set(name, (totals.get(name) ?? 0) + profile.timeDeltas[i] / 1000)
      }
      console.log('Sweep browser CPU ms ' + JSON.stringify([...totals].sort((a, b) => b[1] - a[1]).slice(0, 30)))
      await profiler.detach()
    }
    const applyStart = Date.now()
    await page.locator('#sweep-apply').click()
    await expect(page.locator('#sweep-panel')).not.toBeVisible({ timeout: 30_000 })
    const applyMs = Date.now() - applyStart
    await open()
    await page.locator('#sweep-cancel').click() // Previous to footprint
    const cancelStart = Date.now()
    await page.locator('#sweep-cancel').click()
    await expect(page.locator('#sweep-panel')).not.toBeVisible()
    const cancelMs = Date.now() - cancelStart
    const sorted = [...samples].sort((a, b) => a - b), p95 = sorted[Math.ceil(sorted.length * .95) - 1]
    const requests = await page.evaluate(() => window.__sweepEvaluateTimings)
    expect(requests).toHaveLength(samples.length)
    console.log(`C8 sweep-${large ? 'large' : 'small'} GPU raster excluded ` + JSON.stringify({ samples, p95, applyMs, cancelMs, requests }))
    expect(p95).toBeLessThanOrEqual(1000)
    expect(applyMs).toBeLessThanOrEqual(large ? 20000 : 6000)
    expect(cancelMs).toBeLessThanOrEqual(400)
  }, large ? 'sweep-large' : 'sweep-nick')
})
