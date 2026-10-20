import { test, expect } from '@playwright/test'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { withHeldResponse, withHistoryFixture } from './helpers/deformation_history.js'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Run only through the dedicated launcher/config: the ordinary app's gates are off.
const root = process.env.NADOC_HISTORY_E2E_ROOT
test.skip(!root, 'Requires the isolated history launcher; production gates stay false')
const endpoint = 'http://127.0.0.1:8004/api'
const previewPath = '/api/design/features/deformation-preview'

// GET geometry and compact mutation responses differ in ordering and optional
// metadata. Compare every shared native identity/placement field exactly, not
// whole wire objects or a tolerant geometry summary. Hash only bounds diagnostics.
function placementDigest(geometry) {
  const fields = ['helix_id', 'direction', 'bp_index', 'copy_k', 'strand_id', 'strand_type',
    'domain_index', 'is_five_prime', 'is_three_prime', 'overhang_id', 'placement_source',
    'backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']
  const rows = geometry.map(nuc => fields.map(field => {
    expect(Object.hasOwn(nuc, field), field).toBe(true)
    return nuc[field]
  })).sort((a, b) => JSON.stringify(a.slice(0, 4)).localeCompare(JSON.stringify(b.slice(0, 4))))
  expect(new Set(rows.map(row => JSON.stringify(row.slice(0, 4)))).size).toBe(rows.length)
  return { count: rows.length, sha256: createHash('sha256').update(JSON.stringify(rows)).digest('hex') }
}

for (const kind of ['bend', 'twist']) test(`${kind} history Open/edit/Cancel/Apply`, async ({ page, request }) => {
  const doc = `__e2e__history-${kind}`
  const headers = { 'X-NADOC-Doc': doc }
  const errors = trackConsoleErrors(page)
  const writes = []
  let step = 'seed fixture'
  let primaryFailure = false
  const events = []
  const record = message => {
    events.push(String(message).slice(0, 400))
    if (events.length > 40) events.shift()
  }
  page.on('console', message => {
    if (['error', 'warning'].includes(message.type())) record(`console ${message.type()}: ${message.text()}`)
  })
  page.on('pageerror', error => record(`pageerror: ${error.message}`))
  page.on('response', response => {
    const url = new URL(response.url())
    if (url.pathname.startsWith('/api/design') || response.status() >= 400) record(`${response.status()} ${response.request().method()} ${url.pathname}`)
  })
  page.on('requestfailed', request => record(`requestfailed ${new URL(request.url()).pathname}: ${request.failure()?.errorText}`))
  page.on('request', req => {
    if (req.method() !== 'GET' && new URL(req.url()).pathname.startsWith('/api/design/'))
      writes.push(new URL(req.url()).pathname)
  })
  const checkpoint = async () => {
    const response = await request.get(`${endpoint}/__e2e__/history/checkpoint`, { headers })
    expect(response.ok()).toBe(true)
    return response.json()
  }
  const browser = () => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const api = await import('/src/api/client.js')
    const s = store.getState()
    return { design: s.currentDesign, geometry: s.currentGeometry,
      revision: api.currentRevisionWatermark(),
      saved: Object.fromEntries(Object.keys(localStorage).filter(k => k.startsWith('nadoc:design:'))
        .sort().map(k => [k, localStorage.getItem(k)])) }
  })
  const privateDisplay = () => page.evaluate(() => {
    const roots = window.__nadocTest.scene.children.filter(n => n.name === 'privateDeformationPreview')
    const matrices = []
    for (const root of roots.filter(n => n.visible)) root.traverse(n => {
      if (n.isInstancedMesh && n.count) matrices.push(Array.from(n.instanceMatrix.array))
    })
    return { roots: roots.length, matrices }
  })
  try {
    expect((await request.post(`${endpoint}/__e2e__/history/seed/${kind}`, { headers })).ok()).toBe(true)
    step = 'navigate'
    // A bare ?doc selects the backend session but intentionally boots at welcome.
    // Reuse the existing read-only handoff: GET design/geometry, unlock controls.
    // "simulation" reveals a sidebar only; it never starts a calculation.
    await page.goto(`/?doc=${doc}&readiness=simulation`)
    step = 'wait for adopted geometry'
    await page.waitForFunction(() => window.__nadocTest?.store.getState().currentGeometry?.length > 0)
    await page.waitForFunction(() => !new URL(location.href).searchParams.has('readiness'))
    step = 'save fixture'
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.getDesign()
      if (!await api.saveDesign(file)) throw new Error('Fixture save failed')
    }, path.join(root, 'workspace', `${doc}.nadoc`))
    step = 'open feature log'
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const before = await checkpoint(), stored = await browser()
    expect(before.design.helices).toHaveLength(1)
    expect(before.redo).toHaveLength(1)
    expect(Object.keys(before.files).length).toBeGreaterThan(0)
    const popup = page.locator('.tool-popup[data-tool-panel="deform-panel"]')
    const edit = page.locator('[title="Edit this feature"]').last()
    const input = page.locator(kind === 'bend' ? '#def-bend-angle' : '#def-twist-value')
    const open = async () => {
      step = 'Open private preview'
      const prepared = page.waitForResponse(r => new URL(r.url()).pathname === previewPath && r.request().method() === 'POST')
      await edit.click()
      expect((await prepared).ok()).toBe(true)
      await expect(popup).toBeVisible()
      await expect.poll(async () => (await privateDisplay()).roots).toBe(2)
      expect((await privateDisplay()).matrices.length).toBeGreaterThan(0)
      return (await prepared).json()
    }
    const change = async () => {
      step = 'evaluate changed input'
      const evaluated = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
      await input.fill('35'); await input.press('Tab')
      expect((await evaluated).ok()).toBe(true)
      await expect(page.locator('#def-apply-btn')).toBeEnabled()
    }
    writes.length = 0
    await open()
    expect(await checkpoint()).toEqual(before)
    const originalDisplay = await privateDisplay()
    await change()
    await expect.poll(privateDisplay).not.toEqual(originalDisplay)
    expect(await checkpoint()).toEqual(before)
    expect(await browser()).toEqual(stored)
    step = 'preview off/on preserves source and restores candidate'
    const candidateDisplay = await privateDisplay()
    for (const enabled of [false, true]) {
      const evaluated = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
      await page.locator('#def-preview-check').setChecked(enabled)
      const response = await evaluated
      expect(response.ok()).toBe(true)
      expect(response.request().postDataJSON().include_geometry).toBe(enabled)
      const packet = await response.json()
      expect(packet.feasibility).toBeTruthy()
      if (!enabled) expect(packet.candidate).toBeNull()
      await expect.poll(async () => (await privateDisplay()).roots).toBe(enabled ? 2 : 1)
      if (enabled) expect(await privateDisplay()).toEqual(candidateDisplay)
      else {
        expect((await privateDisplay()).matrices.length).toBeGreaterThan(0)
        expect(await privateDisplay()).not.toEqual(candidateDisplay)
      }
      expect(await checkpoint()).toEqual(before)
      expect(await browser()).toEqual(stored)
    }
    step = 'Cancel and preservation checks'
    await page.locator('#def-cancel-btn').click()
    await expect(popup).not.toBeVisible()
    await expect.poll(async () => (await privateDisplay()).roots).toBe(0)
    expect(await checkpoint()).toEqual(before)
    expect(await browser()).toEqual(stored)
    expect(writes.every(url => url.startsWith(previewPath))).toBe(true)
    expect(writes.filter(url => url.endsWith('/apply'))).toHaveLength(0)

    step = 'repeat Open/Cancel disposal'
    await open()
    await page.locator('#def-cancel-btn').click()
    await expect(popup).not.toBeVisible()
    await expect.poll(async () => (await privateDisplay()).roots).toBe(0)
    expect(await checkpoint()).toEqual(before)
    expect(await browser()).toEqual(stored)
    expect(writes.every(url => url.startsWith(previewPath))).toBe(true)
    expect(writes.filter(url => url.endsWith('/apply'))).toHaveLength(0)

    await open()
    step = 'Cancel pending evaluation, then reopen before old reply'
    await withHeldResponse(page, `${previewPath}/evaluate`, async ({ ready, release }) => {
      await input.fill('45'); await input.press('Tab')
      expect((await ready).response.ok()).toBe(true)
      const cancelled = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/cancel`)
      await page.locator('#def-cancel-btn').click()
      expect((await cancelled).ok()).toBe(true)
      await expect(popup).not.toBeVisible()
      await expect.poll(async () => (await privateDisplay()).roots).toBe(0)
      expect(await checkpoint()).toEqual(before)
      expect(await browser()).toEqual(stored)
      await open()
      step = 'old evaluation cannot replace reopened preview'
      const replacement = await privateDisplay()
      await release()
      // Let the browser process delivered/aborted fetch completion and render.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      expect(await privateDisplay()).toEqual(replacement)
      expect(await checkpoint()).toEqual(before)
      expect(await browser()).toEqual(stored)
      expect(writes.every(url => url.startsWith(previewPath))).toBe(true)
      expect(writes.filter(url => url.endsWith('/apply'))).toHaveLength(0)
    })
    await page.locator('#def-cancel-btn').click()
    await expect(popup).not.toBeVisible()
    await expect.poll(async () => (await privateDisplay()).roots).toBe(0)

    await open()
    step = 'Apply drains pending evaluation and latest draft'
    await withHeldResponse(page, `${previewPath}/evaluate`, async ({ ready, release }) => {
      await input.fill('35'); await input.press('Tab')
      const first = await ready
      expect(first.response.ok()).toBe(true)
      await input.fill('40'); await input.press('Tab')
      await expect(input).toHaveValue('40')
      const latest = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate` &&
        r.request().postDataJSON().request_sequence > first.body.request_sequence)
      const applied = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/apply`)
      await page.locator('#def-apply-btn').click()
      await expect(page.locator('#def-apply-btn')).toBeDisabled()
      expect(writes.filter(url => url.endsWith('/apply'))).toHaveLength(0)
      expect(await checkpoint()).toEqual(before)
      expect(await browser()).toEqual(stored)
      await release()
      const evaluatedResponse = await latest, appliedResponse = await applied
      expect(evaluatedResponse.ok()).toBe(true)
      expect(appliedResponse.ok()).toBe(true)
      const latestDraft = evaluatedResponse.request().postDataJSON().params
      expect(latestDraft).not.toEqual(first.body.params)
      expect(appliedResponse.request().postDataJSON().params).toEqual(latestDraft)
    })
    step = 'Apply and publication checks'
    await expect(popup).not.toBeVisible()
    await expect.poll(async () => (await privateDisplay()).roots).toBe(0)
    const after = await checkpoint()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(after.design.feature_log.map(row => row.id)).toEqual(before.design.feature_log.map(row => row.id))
    expect(after.design.deformations).not.toEqual(before.design.deformations)
    expect((await browser()).revision).toBe(after.revision)
    expect(writes.filter(url => url === `${previewPath}/apply`)).toHaveLength(1)
    step = 'undo accepted edit'
    const editedBrowser = await browser()
    const invoke = (method, arg) => page.evaluate(async ({ method, arg }) => {
      const api = await import('/src/api/client.js')
      if (!await api[method](arg)) throw new Error(`${method} failed`)
    }, { method, arg })
    await invoke('undo')
    const undone = await checkpoint()
    expect(undone.design.deformations).toEqual(before.design.deformations)
    expect(undone.design.feature_log).toEqual(before.design.feature_log)
    expect(undone.history).toHaveLength(before.history.length)
    expect(undone.redo).toHaveLength(1)
    expect(placementDigest((await browser()).geometry)).toEqual(placementDigest(stored.geometry))
    step = 'redo accepted edit'
    await invoke('redo')
    const redone = await checkpoint()
    expect(redone.design.deformations).toEqual(after.design.deformations)
    expect(redone.design.feature_log).toEqual(after.design.feature_log)
    expect(redone.history).toHaveLength(after.history.length)
    expect(redone.redo).toHaveLength(0)
    expect(placementDigest((await browser()).geometry)).toEqual(placementDigest(editedBrowser.geometry))
    step = 'save edited fixture and reopen from different state'
    const savedPath = path.join(root, 'workspace', `${doc}-edited.nadoc`)
    await invoke('saveDesign', savedPath)
    await invoke('undo')
    expect((await checkpoint()).design.deformations).toEqual(before.design.deformations)
    await invoke('loadDesign', savedPath)
    const reopened = await checkpoint(), reopenedBrowser = await browser()
    expect(reopened.design.deformations).toEqual(after.design.deformations)
    expect(reopened.design.feature_log).toEqual(after.design.feature_log)
    expect(reopenedBrowser.design.deformations).toEqual(after.design.deformations)
    expect(placementDigest(reopenedBrowser.geometry)).toEqual(placementDigest(editedBrowser.geometry))
    expect(reopenedBrowser.revision).toBe(reopened.revision)
    step = 'ordinary close/load while Open response is pending'
    await withHeldResponse(page, previewPath, async ({ ready, release }) => {
      await edit.click()
      const old = await ready
      expect(old.response.ok()).toBe(true)
      await page.evaluate(async file => {
        const api = await import('/src/api/client.js')
        await api.closeSession()
        if (!await api.loadDesign(file)) throw new Error('Reset fixture reload failed')
      }, savedPath)
      await expect(popup).not.toBeVisible()
      await expect.poll(async () => (await privateDisplay()).roots).toBe(0)
      const reset = await checkpoint()
      expect(reset.design.id).toBe(reopened.design.id)
      expect(reset.design.deformations).toEqual(after.design.deformations)
      expect(reset.design.feature_log).toEqual(after.design.feature_log)
      expect(placementDigest((await browser()).geometry)).toEqual(placementDigest(editedBrowser.geometry))
      const fresh = await open()
      expect(fresh.preview_id).not.toBe(old.body.preview_id)
      step = 'old Open cannot replace reloaded source or fresh preview'
      const resetBrowser = await browser(), resetDisplay = await privateDisplay()
      await release()
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      expect(await checkpoint()).toEqual(reset)
      expect(await browser()).toEqual(resetBrowser)
      expect(await privateDisplay()).toEqual(resetDisplay)
      expect(writes.filter(url => url === `${previewPath}/apply`)).toHaveLength(1)
    })
    await page.locator('#def-cancel-btn').click()
    await expect(popup).not.toBeVisible()
    await expect.poll(async () => (await privateDisplay()).roots).toBe(0)
    expect(errors).toEqual([])
  } catch (error) {
    primaryFailure = true
    console.error(JSON.stringify({ kind, step, primary: error.message, events }))
    throw error
  } finally {
    // A timed-out test may already have closed its request context. Cleanup must
    // not replace the primary failure; the launcher also drops the whole server.
    const cleanupErrors = []
    try { await page.close() } catch (error) { cleanupErrors.push(error) }
    // File/project-store cleanup belongs to the launcher's finally, after servers
    // stop. It removes the entire fresh workspace even on test/startup failure.
    try {
      const response = await request.delete(`${endpoint}/documents/${doc}`, { timeout: 5000 })
      if (!response.ok()) throw new Error(`Document cleanup HTTP ${response.status()}`)
    } catch (error) { cleanupErrors.push(error) }
    if (cleanupErrors.length) {
      console.error(JSON.stringify({ kind, cleanup: cleanupErrors.map(error => error.message) }))
      if (!primaryFailure) throw cleanupErrors[0]
    }
  }
})

test('History reorder native rows commit undo redo reopen', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.locator('#fl-list [title="Move F1"]').click()
    const dialog = page.getByRole('dialog', { name: 'Move F1', exact: true })
    await dialog.getByLabel('New feature position').selectOption('2')
    await dialog.getByRole('button', { name: 'Move', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect.poll(async () => (await f.browser()).design.feature_log.map(e => e.id)).toEqual(['b', 'c', 'a'])
    const after = await f.checkpoint()
    expect(after.history).toHaveLength(before.history.length + 1)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect((await proof.json()).status).toBe('reproduced_import')
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.browser()).design.feature_log.map(e => e.id)).toEqual(['a', 'b', 'c'])
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.browser()).design.feature_log.map(e => e.id)).toEqual(['b', 'c', 'a'])
  }, 'history-reorder')
})


test('History reorder refuses a geometry dependency without changing the design', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.locator('#fl-list [title="Move F2"]').click()
    const dialog = page.getByRole('dialog', { name: 'Move F2', exact: true })
    await dialog.getByLabel('New feature position').selectOption('0')
    await dialog.getByRole('button', { name: 'Move', exact: true }).click()
    await expect(dialog.getByRole('status')).toContainText('initial bundle')
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  })
})

test('Scoped Bend Twist reorder preserves geometry and downstream Sweep through reopen', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), original = await f.browser()
    const index = original.design.feature_log.findIndex(entry => entry.id === 'edited-feature')
    const expected = original.design.feature_log.map(entry => entry.id)
    ;[expected[index], expected[index + 1]] = [expected[index + 1], expected[index]]
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.locator(`#fl-list [title="Move F${index + 1}"]`).click()
    const dialog = page.getByRole('dialog', { name: `Move F${index + 1}`, exact: true })
    await dialog.getByLabel('New feature position').selectOption(String(index + 1))
    await dialog.getByRole('button', { name: 'Move', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect.poll(async () => (await f.browser()).design.feature_log.map(entry => entry.id)).toEqual(expected)
    expect((await f.browser()).geometry).toEqual(original.geometry)
    expect((await f.checkpoint()).history).toHaveLength(before.history.length + 1)
    const proof = async () => {
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect((await response.json()).status).toBe('verified')
    }
    await proof()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.browser()).design.feature_log.map(entry => entry.id)).toEqual(original.design.feature_log.map(entry => entry.id))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.browser()).design.feature_log.map(entry => entry.id)).toEqual(expected)
    expect((await f.browser()).geometry).toEqual(original.geometry)
    await proof()
  }, 'history-scoped-order')
})

test('Sweep and Extrude history reorder regenerates and persists', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.locator('#fl-list [title="Move F2"]').click()
    const dialog = page.getByRole('dialog', { name: 'Move F2', exact: true })
    await dialog.getByLabel('New feature position').selectOption('2')
    await dialog.getByRole('button', { name: 'Move', exact: true }).click()
    await expect(dialog).toBeHidden()
    const ids = () => f.browser().then(state => state.design.feature_log.map(entry => entry.id))
    await expect.poll(ids).toEqual(['bundle', 'later-extrusion', 'selected-sweep'])
    expect((await f.checkpoint()).history).toHaveLength(before.history.length + 1)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.loadDesign(file)
    }, f.file)
    expect(await ids()).toEqual(['bundle', 'later-extrusion', 'selected-sweep'])
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect((await proof.json()).status).toBe('verified')
  }, 'sweep-extrude')
})

for (const [kind, seed, index] of [
  ['Bend', 'history-scoped-order', 3], ['Twist', 'history-scoped-order', 4],
  ['Sweep', 'sweep-extrude', 1], ['Extrude', 'sweep-extrude', 2],
]) test(`${kind} history suppression undo reopen and unsuppress`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), original = await f.browser()
    const ids = original.design.feature_log.map(entry => entry.id)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const toggle = async action => {
      await page.locator(`#fl-list [title="${action} F${index + 1}"]`).click()
      const dialog = page.getByRole('dialog', { name: `${action} F${index + 1}`, exact: true })
      await dialog.getByRole('button', { name: action, exact: true }).click()
      await expect(dialog).toBeHidden()
    }
    await toggle('Suppress')
    await expect.poll(async () => (await f.browser()).design.feature_log[index].suppressed).toBe(true)
    expect((await f.browser()).design.feature_log.map(entry => entry.id)).toEqual(ids)
    expect((await f.checkpoint()).history).toHaveLength(before.history.length + 1)
    await page.evaluate(async () => (await import('/src/api/client.js')).undo())
    expect((await f.browser()).design.feature_log[index].suppressed).toBe(false)
    expect(placementDigest((await f.browser()).geometry)).toEqual(placementDigest(original.geometry))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo()
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.loadDesign(file)
    }, f.file)
    expect((await f.browser()).design.feature_log[index].suppressed).toBe(true)
    const proof = async () => {
      const response = await request.get(`${endpoint}/__e2e__/history/proof`, { headers: f.headers })
      expect((await response.json()).status).toBe('verified')
    }
    await proof()
    await toggle('Unsuppress')
    expect((await f.browser()).design.feature_log.map(entry => entry.id)).toEqual(ids)
    expect(placementDigest((await f.browser()).geometry)).toEqual(placementDigest(original.geometry))
    await proof()
  }, seed)
})

test('History suppression refuses missing producers atomically', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), original = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.locator('#fl-list [title="Suppress F1"]').click()
    const dialog = page.getByRole('dialog', { name: 'Suppress F1', exact: true })
    await dialog.getByRole('button', { name: 'Suppress', exact: true }).click()
    await expect(dialog.getByRole('status')).toContainText('cannot regenerate')
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(original)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  }, 'history-scoped-order')
})

for (const [name, seed, field, collection] of [
  ['Sweep', 'repair-sweep-source', 'source_helix_id', 'helices'],
  ['Extrude', 'repair-extrude-source', 'source_frame_id', 'lattice_frames'],
]) test(`${name} source reference repair uses prefix selection and survives reopen`, async ({ page, request }) => {
  test.setTimeout(120000) // Same multi-step saved-proposal scope as part_repair.spec.js.
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const original = await f.browser(), feature = original.design.feature_log[1]
    const replacement = original.design[collection][0].id
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByRole('button', { name: /^(?:Check \/ repair recipe|Repair · saved proposal)$/ }).click()
    const panel = page.getByRole('dialog').filter({ hasText: 'Check and repair part recipe' })
    await panel.getByLabel('Feature to repair').selectOption(JSON.stringify([feature.id, null]))
    await panel.locator(`[data-repair-path='["${field}"]']`).getByRole('button', { name: 'Find replacements', exact: true }).click()
    await panel.getByRole('button').filter({ hasText: `(${replacement})` }).click()
    await panel.getByRole('button', { name: 'Save proposal', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Evaluate proposal', exact: true })).toBeEnabled()
    await panel.getByRole('button', { name: 'Evaluate proposal', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true })).toBeEnabled({ timeout: 15000 })
    expect((await f.browser()).design.feature_log[1].params[field]).toBe('missing-source')
    expect(placementDigest((await f.browser()).geometry)).toEqual(placementDigest(original.geometry))
    const beforeApply = await f.checkpoint()
    await panel.getByRole('button', { name: 'Apply evaluated proposal', exact: true }).click()
    await expect.poll(async () => (await f.browser()).design.feature_log[1].params[field]).toBe(replacement)
    expect((await f.checkpoint()).history).toHaveLength(beforeApply.history.length + 1)
    await panel.getByRole('button', { name: 'Close', exact: true }).click()
    expect(placementDigest((await f.browser()).geometry)).toEqual(placementDigest(original.geometry))
    await page.evaluate(async () => (await import('/src/api/client.js')).undo())
    expect((await f.browser()).design.feature_log[1].params[field]).toBe('missing-source')
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo()
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.loadDesign(file)
    }, f.file)
    expect((await f.browser()).design.feature_log[1].params[field]).toBe(replacement)
    const proof = await request.get(`${endpoint}/__e2e__/history/proof`, { headers: f.headers })
    expect((await proof.json()).status).toBe('verified')
  }, seed)
})
