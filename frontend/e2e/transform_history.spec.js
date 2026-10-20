import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'
import { stat } from 'node:fs/promises'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')
const previewPath = '/api/design/features/transform-preview'

for (const size of ['small', 'large'])
test(`Move Rotate ${size} preview Apply and Cancel latency`, async ({ page, request }) => {
  test.setTimeout(240_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const panel = page.locator('#move-rotate-panel'), source = await f.checkpoint()
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === previewPath)
      await page.locator('[title="Edit this move/rotate feature"]').click()
      const response = await pending
      expect(response.ok(), JSON.stringify(await response.json())).toBe(true)
      await expect(panel).toBeVisible()
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    }
    console.log(`C8 transform-${size} ` + JSON.stringify({ file: f.file, bytes: (await stat(f.file)).size,
      helices: source.design.helices.length, strands: source.design.strands.length, gpuRaster: 'excluded (SwiftShader)' }))
    await open()
    const profiler = process.env.NADOC_TRANSFORM_PROFILE ? await page.context().newCDPSession(page) : null
    if (profiler) { await profiler.send('Profiler.enable'); await profiler.send('Profiler.start') }
    const evaluations = []
    const record = response => {
      if (new URL(response.url()).pathname === `${previewPath}/evaluate`)
        evaluations.push({ status: response.status(), sequence: response.request().postDataJSON().request_sequence })
    }
    page.on('response', record)
    const p95s = []
    for (const [tool, selector] of [['move', '#mr-tx'], ['rotate', '#mr-rz']]) {
      const samples = []
      for (const value of [32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54]) {
        samples.push(await page.evaluate(async ({ selector, value }) => {
          const roots = () => window.__nadocTest.scene.children
            .filter(n => n.name === 'privateTransformPreview').map(n => n.uuid).join()
          const before = roots(), input = document.querySelector(selector), start = performance.now()
          input.value = String(value)
          input.dispatchEvent(new Event('input', { bubbles: true }))
          input.dispatchEvent(new Event('change', { bubbles: true }))
          await new Promise((resolve, reject) => {
            const tick = () => roots() !== before ? resolve()
              : performance.now() - start > 20_000 ? reject(new Error('transform preview did not update')) : setTimeout(tick, 4)
            tick()
          })
          return performance.now() - start
        }, { selector, value }))
        await expect(page.locator('#mr-apply-btn')).toBeEnabled()
      }
      const p95 = [...samples].sort((a, b) => a - b)[Math.ceil(samples.length * .95) - 1]
      p95s.push({ tool, p95 })
      console.log(`C8 ${tool}-${size} update_ms=${samples.map(Math.round).join(',')} p95=${Math.round(p95)}`)
    }
    page.off('response', record)
    if (profiler) {
      const { profile } = await profiler.send('Profiler.stop')
      const nodes = new Map(profile.nodes.map(node => [node.id, node.callFrame])), totals = new Map()
      for (let i = 0; i < profile.samples.length; i++) {
        const frame = nodes.get(profile.samples[i])
        const name = `${frame.functionName} ${frame.url}:${frame.lineNumber}`
        totals.set(name, (totals.get(name) ?? 0) + profile.timeDeltas[i] / 1000)
      }
      console.log('DIAGNOSTIC transform CPU ms (not C8 qualification)', [...totals].sort((a, b) => b[1] - a[1]).slice(0, 30))
      await profiler.detach()
    }
    expect(evaluations).toHaveLength(24)
    expect(evaluations.every(r => r.status === 200)).toBe(true)
    expect(new Set(evaluations.map(r => r.sequence)).size).toBe(24)
    expect(await f.checkpoint()).toEqual(source)
    const applyStart = Date.now()
    await page.locator('#mr-apply-btn').click()
    await expect(panel).not.toBeVisible({ timeout: 30_000 })
    const applyMs = Date.now() - applyStart, committed = await f.checkpoint()
    expect(committed.revision).toBe(source.revision + 1)
    expect((await f.browser()).revision).toBe(committed.revision)
    await open()
    const canonical = await f.checkpoint(), browser = await f.browser(), reads = []
    const recordRead = req => {
      if (req.method() === 'GET' && ['/api/design', '/api/design/geometry'].includes(new URL(req.url()).pathname)) reads.push(req.url())
    }
    page.on('request', recordRead)
    const writes = f.writes.length, cancelStart = Date.now()
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    const cancelMs = Date.now() - cancelStart
    page.off('request', recordRead)
    expect(reads).toEqual([])
    expect(await f.checkpoint()).toEqual(canonical)
    expect(await f.browser()).toEqual(browser)
    expect(f.writes.slice(writes).every(r => r.path === `${previewPath}/cancel`)).toBe(true)
    console.log(`C8 transform-${size} apply_ms=${applyMs} cancel_ms=${cancelMs}`)
    for (const { tool, p95 } of p95s) expect.soft(p95, `${tool} preview p95 including 2x allowance`).toBeLessThanOrEqual(1000)
    expect.soft(applyMs, 'Apply including 2x allowance').toBeLessThanOrEqual(size === 'large' ? 20000 : 6000)
    expect.soft(cancelMs, 'Cancel including 2x allowance').toBeLessThanOrEqual(400)
  }, `transform-${size}`, { pauseRendering: true })
})

for (const entry of ['menu', 'shortcut'])
test(`Move Rotate ${entry} creation previews Cancel and creates one replayable feature`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const panel = page.locator('#move-rotate-panel'), before = await f.checkpoint()
    const id = before.design.feature_log.find(e => e.id === 'selected-transform').cluster_id
    const owner = design => design.cluster_transforms.find(c => c.id === id)
    const open = async () => {
      await page.evaluate(async id => {
        const { store } = await import('/src/state/store.js')
        const { createSelectionController } = await import('/src/scene/selection_controller.js')
        createSelectionController({ store }).replace([{ kind: 'cluster', id }])
        document.activeElement?.blur()
      }, id)
      if (entry === 'menu') {
        await page.getByRole('button', { name: 'Tools', exact: true }).hover()
        await page.locator('#menu-tools-translate-rotate').click()
      } else await page.keyboard.press('m')
      await expect(panel).toBeVisible()
      await expect(page.locator('#mr-tx')).toBeEnabled()
    }
    const move = async () => {
      await page.locator('#mr-tx').fill('9')
      await page.locator('#mr-tx').press('Tab')
      await page.locator('#mr-rz').fill('45')
      await page.locator('#mr-rz').press('Tab')
    }
    await open(); await move()
    expect(await f.checkpoint()).toEqual(before)
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    await open(); await move()
    await page.locator('#mr-apply-btn').click()
    await expect.poll(async () => (await f.checkpoint()).design.feature_log.length).toBe(before.design.feature_log.length + 1)
    const after = await f.checkpoint(), created = after.design.feature_log.at(-1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(created.feature_type).toBe('cluster_op')
    expect(created.proof_version).toBe(1)
    expect(created.cluster_id).toBe(id)
    expect(owner(after.design).translation[0]).toBe(9)
    expect(owner(after.design).rotation).not.toEqual(owner(before.design).rotation)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(owner((await f.checkpoint()).design)).toEqual(owner(before.design))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(owner((await f.checkpoint()).design)).toEqual(owner(after.design))
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
  }, 'transform-owner')
})

test('Move and Rotate historical owner edit Cancel Apply downstream undo and reopen', async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const panel = page.locator('#move-rotate-panel')
    const checkpoint = await f.checkpoint(), browser = await f.browser()
    const selected = checkpoint.design.feature_log.find(e => e.id === 'selected-transform')
    const suffix = checkpoint.design.feature_log.at(-1)
    const owner = design => design.cluster_transforms.find(c => c.id === selected.cluster_id)
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const prepared = page.waitForResponse(r => new URL(r.url()).pathname === previewPath)
      await page.locator('[title="Edit this move/rotate feature"]').click()
      const response = await prepared
      expect(response.ok()).toBe(true)
      await expect(panel).toBeVisible()
      await expect(page.locator('#mr-tx')).toBeEnabled()
    }
    const change = async (field, value) => {
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
      await page.locator(field).fill(String(value))
      await page.locator(field).press('Tab')
      const response = await pending
      expect(response.ok()).toBe(true)
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    }
    const proof = async () => {
      const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(response.ok()).toBe(true)
      expect((await response.json()).status).toBe('verified')
    }
    await proof()
    await open()
    await change('#mr-tx', 7)
    await change('#mr-rz', 45)
    expect(await f.checkpoint()).toEqual(checkpoint)
    expect(await f.browser()).toEqual(browser)
    const startWrites = f.writes.length
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(checkpoint)
    expect(await f.browser()).toEqual(browser)
    expect(f.writes.slice(startWrites).every(write => write.path.endsWith('/transform-preview/cancel'))).toBe(true)

    await open()
    await change('#mr-tx', 7)
    await change('#mr-rz', 45)
    await page.locator('#mr-apply-btn').click()
    await expect(panel).not.toBeVisible()
    const after = await f.checkpoint()
    expect(after.revision).toBe(checkpoint.revision + 1)
    expect(after.history).toHaveLength(checkpoint.history.length + 1)
    expect(owner(after.design).translation[0]).toBe(7)
    expect(owner(after.design).rotation).not.toEqual(owner(checkpoint.design).rotation)
    expect(after.design.feature_log.map(e => e.id)).toEqual(checkpoint.design.feature_log.map(e => e.id))
    expect(after.design.feature_log.at(-1).id).toBe(suffix.id)
    await proof()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(owner((await f.checkpoint()).design)).toEqual(owner(checkpoint.design))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(owner((await f.checkpoint()).design)).toEqual(owner(after.design))
    await proof()
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      if (!await api.seekFeatures(1)) throw new Error('Seek failed')
    })
    await expect(page.locator('[data-fl-row="2"]').getByTitle('Return to the latest history position before editing feature inputs.', { exact: true })).toBeDisabled()
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      if (!await api.seekFeatures(-1)) throw new Error('Return to tip failed')
    })
    await expect(page.getByTitle('Edit this move/rotate feature', { exact: true })).toBeEnabled()
  }, 'transform-owner')
})

for (const kind of ['joint', 'linked'])
test(`Move Rotate ${kind} controls preserve complete poses and historical constraints`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const panel = page.locator('#move-rotate-panel'), checkpoint = await f.checkpoint(), browser = await f.browser()
    const selected = design => design.feature_log.find(e => e.id === 'selected-transform')
    const original = selected(checkpoint.design).params
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === previewPath)
      await page.getByTitle('Edit placement-poses parameters', { exact: true }).click()
      const response = await pending
      expect(response.ok()).toBe(true)
      await expect(panel).toBeVisible()
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
      return response.json()
    }
    const move = async () => {
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
      pending.catch(() => {}) // Preserve the original gesture error if fixture cleanup closes the page.
      if (kind === 'joint') {
        await page.locator('#mr-ja').fill('90')
        await page.locator('#mr-ja').press('Tab')
      } else {
        // Drive the actual native TransformControls gesture event path in the
        // real app; its linked solver must contribute every accepted pose.
        await page.evaluate(() => {
          const active = window.__nadocTest.scene.children.filter(node => node.controls?.object)
          if (active.length !== 1) throw new Error(`Expected one active native movement gizmo, got ${active.length}`)
          const tc = active[0].controls
          tc.dispatchEvent({ type: 'dragging-changed', value: true })
          tc.object.position.x -= 1
          tc.object.position.y += 1
          tc.object.position.z += .25
          tc.dispatchEvent({ type: 'change' })
          tc.dispatchEvent({ type: 'dragging-changed', value: false })
        })
      }
      const response = await pending
      expect(response.ok()).toBe(true)
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
      return response.request().postDataJSON().params
    }
    const initial = await open()
    if (kind === 'joint') {
      expect(initial.control_state.cluster_joints.find(j => j.id === 'native-hinge').max_angle_deg).toBe(25)
      expect(checkpoint.design.cluster_joints.find(j => j.id === 'native-hinge').max_angle_deg).toBe(75)
    }
    await move()
    expect(await f.checkpoint()).toEqual(checkpoint)
    expect(await f.browser()).toEqual(browser)
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(checkpoint)
    expect(await f.browser()).toEqual(browser)

    await open()
    const patch = await move()
    const primary = patch.poses.find(p => p.cluster_id === original.primary_cluster_id)
    const auxiliary = original.poses.find(p => p.cluster_id !== original.primary_cluster_id)
    expect(patch.poses.map(p => p.cluster_id)).toEqual(original.poses.map(p => p.cluster_id))
    expect(patch.authoring.fixed_cluster_ids).toEqual(original.authoring.fixed_cluster_ids)
    if (kind === 'joint') {
      const halfAngle = 25 * Math.PI / 360
      primary.rotation.forEach((value, i) => expect(value).toBeCloseTo([0, Math.sin(halfAngle), 0, Math.cos(halfAngle)][i], 8))
    } else {
      expect(patch.poses.find(p => p.cluster_id === auxiliary.cluster_id)).not.toEqual(auxiliary)
    }
    await page.locator('#mr-apply-btn').click()
    await expect(panel).not.toBeVisible()
    const after = await f.checkpoint()
    expect(after.revision).toBe(checkpoint.revision + 1)
    expect(after.history).toHaveLength(checkpoint.history.length + 1)
    expect(selected(after.design).params.poses).toEqual(patch.poses)
    expect(after.design.feature_log.map(e => e.id)).toEqual(checkpoint.design.feature_log.map(e => e.id))
    for (const id of original.authoring.fixed_cluster_ids) {
      expect(after.design.cluster_transforms.find(c => c.id === id))
        .toEqual(checkpoint.design.cluster_transforms.find(c => c.id === id))
    }
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo(); await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(selected((await f.checkpoint()).design).params.poses).toEqual(patch.poses)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
  }, `transform-${kind}`)
})

test('Move Rotate injected downstream refusal marks error and blocked rows until Cancel or retry', async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const panel = page.locator('#move-rotate-panel'), before = await f.checkpoint()
    const failedId = 'suffix-fixed-pose'
    const index = before.design.feature_log.findIndex(row => row.id === failedId)
    let refuse = false
    const match = url => url.pathname === `${previewPath}/apply`
    const handler = route => {
      if (!refuse) return route.continue()
      refuse = false
      // Fault injection tests feedback transport/lifecycle only. It is not
      // evidence of a pose edit causing this native downstream command to fail.
      return route.fulfill({ status: 409, contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'missing_reference', feature_id: failedId,
          message: 'Injected downstream reference refusal' } }) })
    }
    await page.route(match, handler)
    try {
      for (const exit of ['cancel', 'retry']) {
        await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
        const opened = page.waitForResponse(r => new URL(r.url()).pathname === previewPath)
        await page.getByTitle('Edit placement-poses parameters', { exact: true }).click()
        expect((await opened).ok()).toBe(true)
        await expect(panel).toBeVisible()
        await expect(page.locator('#mr-apply-btn')).toBeEnabled()
        refuse = true
        const failed = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/apply`)
        await page.locator('#mr-apply-btn').click()
        expect((await failed).status()).toBe(409)
        await expect(panel).toContainText(`F${index + 1} cluster_op cannot regenerate after this edit`)
        await expect(panel).toContainText('Injected downstream reference refusal')
        await expect(page.locator(`[data-fl-row="${index + 1}"] [data-history-status="error"]`)).toHaveText('Edit failed')
        await expect(page.locator(`[data-fl-row="${index + 2}"] [data-history-status="blocked"]`)).toHaveText('Blocked')
        expect(await f.checkpoint()).toEqual(before)
        if (exit === 'cancel') {
          await page.locator('#mr-cancel-btn').click()
          await expect(panel).not.toBeVisible()
          expect(await f.checkpoint()).toEqual(before)
        } else {
          await page.locator('#mr-apply-btn').click()
          await expect(panel).not.toBeVisible()
          expect((await f.checkpoint()).history).toHaveLength(before.history.length + 1)
        }
        await expect(page.locator('[data-history-status]')).toHaveCount(0)
      }
      return { expectedConsoleErrors: Array(2).fill('Failed to load resource: the server responded with a status of 409 (Conflict)') }
    } finally { await page.unroute(match, handler) }
  }, 'transform-joint')
})

for (const [tool, selector, value] of [['Move', '#mr-tx', '9'], ['Rotate', '#mr-rz', '45']])
test(`${tool} native downstream refusal identifies the first error and blocks its descendant`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const before = await f.checkpoint(), panel = page.locator('#move-rotate-panel')
    const selectedIndex = before.design.feature_log.findIndex(row => row.id === 'selected-transform')
    const failedIndex = before.design.feature_log.findIndex(row => row.id === 'later-owner-feature')
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.locator(`[data-fl-row="${selectedIndex + 1}"] [title="Edit this move/rotate feature"]`).click({ timeout: 10_000 })
    await expect(panel).toBeVisible()
    await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    const evaluated = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
    await page.locator(selector).fill(value)
    await page.locator(selector).press('Tab')
    expect((await evaluated).ok()).toBe(true)
    await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    const applied = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/apply`, { timeout: 15_000 })
    await page.locator('#mr-apply-btn').click()
    const response = await applied
    await expect(panel).toContainText('Missing domain in overlay target')
    await expect(page.locator(`[data-fl-row="${failedIndex + 1}"] [data-history-status="error"]`)).toHaveText('Edit failed')
    await expect(page.locator(`[data-fl-row="${failedIndex + 2}"] [data-history-status="blocked"]`)).toHaveText('Blocked')
    expect(await f.checkpoint()).toEqual(before)
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    await expect(page.locator('[data-history-status]')).toHaveCount(0)
    expect(await f.checkpoint()).toEqual(before)
    return { expectedConsoleErrors: response.status() === 409
      ? ['Failed to load resource: the server responded with a status of 409 (Conflict)'] : [] }
  }, 'transform-failure')
})
