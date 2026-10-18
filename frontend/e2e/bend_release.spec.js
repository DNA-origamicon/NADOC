import { test, expect } from '@playwright/test'
import { withHistoryFixture, withHeldResponse, previewPath } from './helpers/deformation_history.js'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')

for (const kind of ['bend', 'twist']) test(`${kind} Cancel after publication before Apply reply`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, kind, async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await f.open()
    await f.change(kind === 'bend' ? '#def-bend-angle' : '#def-twist-value', 35)
    await withHeldResponse(f.page, `${previewPath}/apply`, async ({ ready, release }) => {
      await f.page.locator('#def-apply-btn').click()
      const applied = await ready
      expect(applied.response.ok()).toBe(true)
      const committed = await f.checkpoint()
      expect(committed.revision).toBe(before.revision + 1)
      expect(committed.history).toHaveLength(before.history.length + 1)
      expect(committed.design.deformations).not.toEqual(before.design.deformations)
      expect(await f.browser()).toEqual(stored)
      const cancel = f.page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/cancel`)
      await f.page.locator('#def-cancel-btn').click()
      const receipt = await cancel
      expect(receipt.ok()).toBe(true)
      expect((await receipt.json()).status).toBe('applied')
      expect(await f.checkpoint()).toEqual(committed)
      // Cancellation cannot roll back a published edit. Original Apply retains
      // refresh ownership until its real response arrives.
      await release()
      await expect(f.popup).not.toBeVisible()
      await expect.poll(async () => (await f.display()).roots).toBe(0)
      const adopted = await f.browser()
      expect(adopted.revision).toBe(committed.revision)
      expect(adopted.design.deformations).toEqual(committed.design.deformations)
      expect(adopted.geometry).not.toEqual(stored.geometry)
      expect(await f.checkpoint()).toEqual(committed)
      expect(f.writes.filter(r => r.path === `${previewPath}/apply`)).toHaveLength(1)
    })
  })
})

test('bend history angle radius direction and reversed planes preserve inputs', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await f.open()
    await expect(page.locator('#def-polymer-circle')).toBeDisabled()
    let result = await f.change('#def-bend-angle', 28)
    expect(result.body.params.params.curvature_deg_per_bp).toBe(1)
    await expect(page.locator('#def-bend-radius')).not.toHaveValue('')
    result = await f.change('#def-bend-dir', -90)
    expect(result.body.params.params.direction_deg).toBe(270)
    await f.change('#def-bend-radius', 20)
    await expect(page.locator('#def-bend-radius')).toHaveValue('20')
    await f.change('#def-plane-a-bp', 30, p => p.plane_a_bp === 30)
    result = await f.change('#def-plane-b-bp', 6, p => p.plane_a_bp === 6 && p.plane_b_bp === 30)
    expect(result.body.params.plane_a_bp).toBe(6)
    expect(result.body.params.plane_b_bp).toBe(30)
    expect(result.body.params.params.direction_deg).toBe(270)
    expect(result.packet.feasibility).toBeTruthy()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    // Plane repositioning also updates the displayed angle at the popup's
    // existing six-significant-digit precision. Apply must persist these final
    // visible inputs exactly, rather than an earlier intermediate evaluation.
    const finalAngle = Number(await page.locator('#def-bend-angle').inputValue())
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    const after = await f.checkpoint(), op = after.design.deformations.at(-1)
    expect(op.plane_a_bp).toBe(6); expect(op.plane_b_bp).toBe(30)
    expect(op.params).toEqual({ kind: 'bend', curvature_deg_per_bp: finalAngle / 24, direction_deg: 270 })
    expect(after.revision).toBe(before.revision + 1)
    await f.open()
    await expect(page.locator('#def-plane-a-bp')).toHaveValue('6')
    await expect(page.locator('#def-plane-b-bp')).toHaveValue('30')
    await expect(page.locator('#def-bend-dir')).toHaveValue('270')
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(after)
  })
})

for (const kind of ['bend', 'twist']) test(`${kind} toolbar creation selection Clear Cancel Apply undo and reopen`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, kind, async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const valueInput = kind === 'bend' ? '#def-bend-angle' : '#def-twist-value'
    const select = () => page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      createSelectionController({ store }).replace([{ kind: 'strand', id: store.getState().currentDesign.strands[0].id }])
    })
    const launch = async () => {
      await page.getByRole('button', { name: 'Tools', exact: true }).hover()
      await page.locator(`#menu-tools-${kind}`).click()
      await expect(f.popup).toBeVisible()
    }
    await launch()
    await expect(page.locator('#def-apply-btn')).toBeDisabled()
    await select()
    await expect(page.locator('#def-apply-btn')).toBeEnabled()
    await f.change(valueInput, 15)
    await page.locator('#def-change-selection').click()
    await expect(page.locator('#def-apply-btn')).toBeDisabled()
    await page.locator('#def-clear-selection').click()
    await expect(page.locator('#def-apply-btn')).toBeDisabled()
    expect(await f.checkpoint()).toEqual(before)
    await select()
    await expect(page.locator('#def-apply-btn')).toBeEnabled()
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    await launch()
    await expect(page.locator('#def-apply-btn')).toBeEnabled()
    await f.change(valueInput, 20)
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    const after = await f.checkpoint()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.design.feature_log).toHaveLength(before.design.feature_log.length + 1)
    expect(after.design.deformations).toHaveLength(before.design.deformations.length + 1)
    const created = after.design.deformations.at(-1)
    expect(created.type).toBe(kind)
    if (kind === 'twist') expect(created.params).toEqual({ kind: 'twist', total_degrees: 20, degrees_per_nm: null })
    expect(created.targets).toEqual([{ kind: 'strand', id: before.design.strands[0].id }])
    expect(created.target_ranges.length).toBeGreaterThan(0)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(before.design.deformations)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(after.design.deformations)
    await f.open()
    await expect(page.locator('#def-current-selection')).toContainText('Strand')
    expect(Number(await page.locator(valueInput).inputValue())).toBe(20)
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    expect(f.writes.filter(r => r.path === `${previewPath}/apply`)).toHaveLength(1)
    expect(f.writes.some(r => /\/design\/deformation(?:\/|$)/.test(r.path))).toBe(false)
  })
})

const endpoint = 'http://127.0.0.1:8004/api/__e2e__/history'
async function readFixture(f, name) {
  const r = await f.request.get(`${endpoint}/${name}`, { headers: f.headers })
  expect(r.ok()).toBe(true)
  return r.json()
}

test('bend edit replays a later native Twist and survives save undo redo reload', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint()
    expect(before.design.helices).toHaveLength(4)
    expect((await readFixture(f, 'proof')).status).toBe('verified')
    await f.open(0)
    await f.change('#def-bend-angle', 20)
    expect(await f.checkpoint()).toEqual(before)
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    const after = await f.checkpoint()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.design.feature_log.map(e => e.id)).toEqual(before.design.feature_log.map(e => e.id))
    expect(after.design.deformations[0]).not.toEqual(before.design.deformations[0])
    expect(after.design.deformations[1]).toEqual(before.design.deformations[1])
    expect((await readFixture(f, 'proof')).status).toBe('verified')
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(before.design.deformations)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(after.design.deformations)
    expect((await readFixture(f, 'proof')).status).toBe('verified')
  }, 'bend-chain')
})

test('bend fixed limit repeated sessions release resources and publish once', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), samples = []
    expect(before.design.helices).toHaveLength(16)
    for (let cycle = 0; cycle < 3; cycle++) {
      const start = Date.now()
      await f.open()
      const opened = Date.now()
      const evaluate = f.change('#def-bend-angle', 12 + cycle)
      const readStart = Date.now()
      const read = await request.get('http://127.0.0.1:8004/api/design/revision', { headers: f.headers })
      expect(read.ok()).toBe(true)
      const readMs = Date.now() - readStart
      await evaluate
      const evaluated = Date.now()
      await page.locator('#def-cancel-btn').click()
      await expect(f.popup).not.toBeVisible()
      await expect.poll(async () => (await f.display()).roots).toBe(0)
      const resources = await readFixture(f, 'resources')
      expect(resources.document_sessions).toBe(0)
      expect(resources.sessions).toBeLessThanOrEqual(2)
      expect(resources.tombstones).toBeLessThanOrEqual(16)
      expect(await f.checkpoint()).toEqual(before)
      samples.push({ cycle, open_ms: opened - start, evaluate_ms: evaluated - opened,
        concurrent_read_ms: readMs, cancel_ms: Date.now() - evaluated, ...resources })
    }
    await f.open()
    await f.change('#def-bend-angle', 16)
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    const after = await f.checkpoint()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect((await readFixture(f, 'proof')).status).toBe('verified')
    console.log('BEND_LIMIT_SAMPLES', JSON.stringify(samples))
  }, 'bend-limit')
})

test('bend over fixed helix limit refuses without canonical mutation', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint()
    expect(before.design.helices).toHaveLength(17)
    const response = await request.post(`http://127.0.0.1:8004${previewPath}`, { headers: f.headers,
      data: { preview_id: crypto.randomUUID(), expected_design_id: before.design.id,
        expected_revision: before.revision, feature_id: 'edited-feature' } })
    expect(response.status()).toBe(413)
    expect(JSON.stringify(await response.json())).toContain('preview_limit')
    expect(await f.checkpoint()).toEqual(before)
    expect((await readFixture(f, 'resources')).document_sessions).toBe(0)
  }, 'bend-over-limit')
})

for (const kind of ['bend', 'twist'])
for (const surface of ['sidebar', 'context']) test(`${kind} end-menu ${surface} preserves explicit scope and placement`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, kind, async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const valueInput = kind === 'bend' ? '#def-bend-angle' : '#def-twist-value'
    const targets = [{ kind: 'strand', id: before.design.strands[0].id }]
    await page.evaluate(async targets => {
      const { store } = await import('/src/state/store.js')
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      createSelectionController({ store }).replace(targets)
      store.setState({ toolFilters: { ...store.getState().toolFilters, bluntEnds: true } })
      window.__nadocTest.applyCameraPoseForTest({ position: [18, 16, 35], target: [0, 0, 7] })
    }, targets)
    const launch = async () => {
      await expect.poll(() => page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions()
        .filter(e => e.openSide === 1).length)).toBeGreaterThan(0)
      const end = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions().find(e => e.openSide === 1))
      await page.mouse.move(end.x, end.y)
      await page.mouse.click(end.x, end.y, { button: surface === 'context' ? 'right' : 'left' })
      const button = page.locator(`#blunt-${kind}-btn${surface === 'context' ? '-ctx' : ''}`)
      await expect(button).toBeVisible()
      const prepared = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/create`)
      await button.click()
      const response = await prepared
      expect(response.ok()).toBe(true)
      await expect(f.popup).toBeVisible()
      await expect(page.locator('#def-plane-b-bp')).toHaveValue(String(end.diskBp - end.openSide))
      await expect(page.locator('#def-plane-a-bp')).toHaveValue(String(Math.min(...before.design.helices.map(h => h.bp_start ?? 0))))
      return { body: response.request().postDataJSON(), packet: await response.json() }
    }
    const prepared = await launch()
    await f.change(valueInput, 20)
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    expect(await f.checkpoint()).toEqual(before)
    expect(f.errors).toEqual([])
    // Cancel evidence remains available even if the launch loses explicit scope.
    expect(prepared.body.targets, 'end placement must preserve explicit strand scope').toEqual(targets)
    expect(prepared.packet.control_context.creation.targets).toEqual(targets)
    await launch()
    await f.change(valueInput, 20)
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    const after = await f.checkpoint()
    expect(after.revision).toBe(before.revision + 1)
    for (const field of ['history']) expect(after[field]).toHaveLength(before[field].length + 1)
    for (const field of ['feature_log', 'deformations']) expect(after.design[field]).toHaveLength(before.design[field].length + 1)
    const created = after.design.deformations.at(-1)
    expect(created.type).toBe(kind)
    if (kind === 'twist') {
      expect(created.params.total_degrees).toBe(20)
      expect(created.params.degrees_per_nm).toBeNull()
    }
    expect(created.targets).toEqual(targets)
    expect(created.target_ranges.length).toBeGreaterThan(0)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(before.design.deformations)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(after.design.deformations)
    await f.open()
    await expect(page.locator('#def-plane-a-bp')).toHaveValue(String(created.plane_a_bp))
    await expect(page.locator('#def-plane-b-bp')).toHaveValue(String(created.plane_b_bp))
    expect(Number(await page.locator(valueInput).inputValue())).toBe(20)
    await expect(page.locator('#def-current-selection')).toContainText('Strand')
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    expect(f.writes.filter(r => r.path === `${previewPath}/apply`)).toHaveLength(1)
    expect(f.writes.some(r => /\/design\/deformation(?:\/|$)/.test(r.path))).toBe(false)
  })
})


test('twist history units handedness and reversed planes persist exact inputs', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'twist', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await f.open()
    const choose = async (selector, matches) => {
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`
        && matches(r.request().postDataJSON().params.params))
      await page.locator(selector).check()
      expect((await pending).ok()).toBe(true)
      await expect(page.locator('#def-apply-btn')).toBeEnabled()
    }
    let evaluated = await f.change('#def-twist-value', 24)
    expect(evaluated.body.params.params).toEqual({ kind: 'twist', total_degrees: 24 })
    await choose('#def-twist-lh', p => p.total_degrees === -24)
    await choose('#def-twist-pernm-radio', p => p.degrees_per_nm === -24)
    evaluated = await f.change('#def-twist-value', 3.5)
    expect(evaluated.body.params.params).toEqual({ kind: 'twist', degrees_per_nm: -3.5 })
    await f.change('#def-plane-a-bp', 30, p => p.plane_a_bp === 30)
    evaluated = await f.change('#def-plane-b-bp', 6, p => p.plane_a_bp === 6 && p.plane_b_bp === 30)
    expect(evaluated.body.params.params).toEqual({ kind: 'twist', degrees_per_nm: -3.5 })
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    const after = await f.checkpoint(), op = after.design.deformations.at(-1)
    expect(op.params).toEqual({ kind: 'twist', total_degrees: null, degrees_per_nm: -3.5 })
    expect(op.plane_a_bp).toBe(6); expect(op.plane_b_bp).toBe(30)
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.design.feature_log.map(e => e.id)).toEqual(before.design.feature_log.map(e => e.id))
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(before.design.deformations)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(after.design.deformations)
    await f.open()
    await expect(page.locator('#def-twist-pernm-radio')).toBeChecked()
    await expect(page.locator('#def-twist-lh')).toBeChecked()
    expect(Number(await page.locator('#def-twist-value').inputValue())).toBe(3.5)
    await expect(page.locator('#def-plane-a-bp')).toHaveValue('6')
    await expect(page.locator('#def-plane-b-bp')).toHaveValue('30')
    const reopened = await f.checkpoint()
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    expect(await f.checkpoint()).toEqual(reopened)
    expect(f.writes.filter(r => r.path === `${previewPath}/apply`)).toHaveLength(1)
    expect(f.writes.some(r => /\/design\/deformation(?:\/|$)/.test(r.path))).toBe(false)
  })
})

for (const kind of ['bend', 'twist']) test(`${kind} lost Apply reply recovers published receipt through Status`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, kind, async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const input = kind === 'bend' ? '#def-bend-angle' : '#def-twist-value'
    await f.open()
    await f.change(input, 35)
    const diagnostics = []
    const capture = message => {
      if (message.type() === 'error') diagnostics.push({ text: message.text(), url: message.location().url })
    }
    page.on('console', capture)
    try {
      await withHeldResponse(page, `${previewPath}/apply`, async ({ ready, release }) => {
        await page.locator('#def-apply-btn').click()
        const applied = await ready
        expect(applied.response.ok()).toBe(true)
        const receipt = await applied.response.json()
        const committed = await f.checkpoint()
        expect(committed.revision).toBe(before.revision + 1)
        expect(committed.history).toHaveLength(before.history.length + 1)
        expect(committed.design.deformations).not.toEqual(before.design.deformations)
        expect(committed.design.feature_log.map(e => e.id)).toEqual(before.design.feature_log.map(e => e.id))
        expect(await f.browser()).toEqual(stored)
        const failed = page.waitForEvent('requestfailed', r => new URL(r.url()).pathname === `${previewPath}/apply`)
        await release()
        const lostRequest = await failed
        expect(lostRequest.failure().errorText).toBe('net::ERR_FAILED')
        await expect(page.locator('#def-history-status')).toContainText('Publication status is unknown')
        await expect(page.locator('#def-apply-btn')).toBeDisabled()
        await expect(page.locator(input)).toBeDisabled()
        await expect(page.locator('#def-history-resolve')).toBeEnabled()
        expect(await f.browser()).toEqual(stored)
        expect(await f.checkpoint()).toEqual(committed)
        const recoveryPaths = [`${previewPath}/status`, '/api/design', '/api/design/geometry', '/api/design/revision']
        const recoveryReads = [], receiptReads = []
        const trackRecovery = req => {
          const pathname = new URL(req.url()).pathname
          if (recoveryPaths.includes(pathname)) recoveryReads.push({ path: pathname, body: req.postDataJSON() })
        }
        const trackReceipt = response => {
          if (new URL(response.url()).pathname === `${previewPath}/status`)
            receiptReads.push(response.json())
        }
        page.on('request', trackRecovery)
        page.on('response', trackReceipt)
        const status = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/status`)
        await page.locator('#def-history-resolve').click()
        const recovered = await status
        expect(recovered.ok()).toBe(true)
        expect(await recovered.json()).toMatchObject(receipt)
        await expect(f.popup).not.toBeVisible()
        await expect.poll(async () => (await f.display()).roots).toBe(0)
        const adopted = await f.browser()
        expect(adopted.revision).toBe(committed.revision)
        expect(adopted.design.deformations).toEqual(committed.design.deformations)
        expect(adopted.geometry).not.toEqual(stored.geometry)
        expect(await f.checkpoint()).toEqual(committed)
        expect(f.writes.filter(r => r.path === `${previewPath}/apply`)).toHaveLength(1)
        page.off('request', trackRecovery)
        page.off('response', trackReceipt)
        // Resolve once, then refreshCommitted brackets its private reads with
        // two exact receipt checks before the controller can adopt the display.
        expect(recoveryReads.map(r => r.path)).toEqual([
          `${previewPath}/status`, `${previewPath}/status`, '/api/design',
          '/api/design/geometry', '/api/design/revision', `${previewPath}/status`,
        ])
        const binding = Object.fromEntries(['preview_id', 'lease_id', 'expected_design_id',
          'expected_revision', 'feature_id'].map(key => [key, receipt[key]]))
        expect(recoveryReads.filter(r => r.path === `${previewPath}/status`).map(r => r.body))
          .toEqual([binding, binding, binding])
        expect(f.writes.filter(r => r.path === `${previewPath}/status`).map(r => r.body))
          .toEqual([binding, binding, binding])
        const receipts = await Promise.all(receiptReads)
        expect(receipts).toHaveLength(3)
        for (const value of receipts) expect(value).toMatchObject(receipt)
        await page.evaluate(async file => {
          const api = await import('/src/api/client.js')
          if (!await api.saveDesign(file)) throw new Error('Save failed')
          await api.undo()
        }, f.file)
        expect((await f.checkpoint()).design.deformations).toEqual(before.design.deformations)
        await page.evaluate(async file => {
          const api = await import('/src/api/client.js')
          await api.redo(); await api.loadDesign(file)
        }, f.file)
        expect((await f.checkpoint()).design.deformations).toEqual(committed.design.deformations)
        await f.open()
        expect(Number(await page.locator(input).inputValue())).toBe(35)
        await page.locator('#def-cancel-btn').click()
        await expect(f.popup).not.toBeVisible()
        await expect.poll(async () => (await f.display()).roots).toBe(0)
        expect(f.writes.some(r => /\/design\/deformation(?:\/|$)/.test(r.path))).toBe(false)
        // Exactly the discarded request's Chromium diagnostic; no filtering.
        expect(diagnostics).toEqual([{ text: 'Failed to load resource: net::ERR_FAILED', url: lostRequest.url() }])
      }, { loseReply: true })
      return { expectedConsoleErrors: ['Failed to load resource: net::ERR_FAILED'] }
    } finally { page.off('console', capture) }
  })
})

for (const kind of ['bend', 'twist']) test(`${kind} edit replays attached downstream Sweep with Cancel and persistence`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, kind, async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    expect(before.redo).toHaveLength(1)
    expect(before.design.feature_log.at(-1).params.source_helix_id).toBe(before.design.helices[0].id)
    expect((await readFixture(f, 'proof')).status).toBe('verified')
    await f.open(0)
    await f.change(kind === 'bend' ? '#def-bend-angle' : '#def-twist-value', 20)
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await f.open(0)
    await f.change(kind === 'bend' ? '#def-bend-angle' : '#def-twist-value', 20)
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(after.design.feature_log.map(e => e.id)).toEqual(before.design.feature_log.map(e => e.id))
    expect(after.design.feature_log.at(-1).params).toEqual(before.design.feature_log.at(-1).params)
    expect(after.design.helices.map(h => h.id)).toEqual(before.design.helices.map(h => h.id))
    expect(adopted.geometry).not.toEqual(stored.geometry)
    const geometry = await page.evaluate(async () => {
      const { _request } = await import('/src/api/client.js')
      return _request('GET', '/design/geometry')
    })
    expect(geometry?.nucleotides).toBeTruthy()
    // Ordinary compact adoption and full reads differ in optional wire metadata.
    // Compare every shared native placement field exactly for every nucleotide.
    const fields = ['helix_id', 'direction', 'bp_index', 'copy_k', 'strand_id', 'strand_type',
      'domain_index', 'is_five_prime', 'is_three_prime', 'overhang_id', 'placement_source',
      'backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']
    const placements = rows => rows.map(row => fields.map(field => {
      expect(Object.hasOwn(row, field), field).toBe(true)
      return row[field]
    })).sort((a, b) => JSON.stringify(a.slice(0, 4)).localeCompare(JSON.stringify(b.slice(0, 4))))
    expect(placements(adopted.geometry)).toEqual(placements(geometry.nucleotides))
    const sweepId = before.design.helices[1].id
    expect(adopted.geometry.filter(n => n.helix_id === sweepId)).not.toEqual(
      stored.geometry.filter(n => n.helix_id === sweepId))
    expect((await readFixture(f, 'proof')).status).toBe('verified')
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(before.design.deformations)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.checkpoint()).design.deformations).toEqual(after.design.deformations)
    expect((await readFixture(f, 'proof')).status).toBe('verified')
    expect(placements((await f.browser()).geometry)).toEqual(placements(adopted.geometry))
  }, `${kind}-sweep`)
})

for (const kind of ['bend', 'twist']) test(`${kind} mid-log creation and history edit refuse without mutation`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, kind, async f => {
    // Seek through the real client; retain the edited deformation and its suffix.
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      if (!await api.seekFeatures(1)) throw new Error('Seek failed')
    })
    const before = await f.checkpoint(), stored = await f.browser()
    expect(before.design.feature_log_cursor).toBe(1)
    expect(before.design.feature_log.length).toBeGreaterThan(2)
    const writesBefore = f.writes.length
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.locator('[title="Edit this feature"]').first().click()
    await expect(page.locator('.toast-message').filter({ hasText: 'History edit unavailable: Choose a feature in the current editable part revision' })).toBeVisible()
    await expect(f.popup).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      createSelectionController({ store }).replace([{ kind: 'strand', id: store.getState().currentDesign.strands[0].id }])
    })
    await page.getByRole('button', { name: 'Tools', exact: true }).hover()
    await page.locator(`#menu-tools-${kind}`).click()
    await expect(page.locator('.toast-message').filter({ hasText: 'Deformation creation unavailable: Choose a feature in the current editable part revision' })).toBeVisible()
    // The existing refusal keeps the selection picker available, with Apply disabled.
    await expect(f.popup).toBeVisible()
    await expect(page.locator('#def-apply-btn')).toBeDisabled()
    await expect(f.popup).toContainText('The isolated deformation preview is unavailable')
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    expect((await f.display()).roots).toBe(0)
    expect(f.writes.slice(writesBefore)).toEqual([])
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    expect(f.writes.slice(writesBefore)).toEqual([])
    // Returning to the tip restores the existing editor without a stale owner.
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      if (!await api.seekFeatures(-1)) throw new Error('Return to tip failed')
    })
    const tip = await f.checkpoint()
    await f.open(0)
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(tip)
  }, `${kind}-sweep`)
})

for (const kind of ['bend', 'twist']) test(`${kind} downstream nick cold replay Cancel undo redo and reopen`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, kind, async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const input = kind === 'bend' ? '#def-bend-angle' : '#def-twist-value'
    expect(before.design.feature_log.at(-1).id).toBe('downstream-nick')
    expect(before.design.strands).toHaveLength(3)
    expect(before.redo).toHaveLength(1)
    const fields = ['helix_id', 'direction', 'bp_index', 'copy_k', 'strand_id', 'strand_type',
      'domain_index', 'is_five_prime', 'is_three_prime', 'overhang_id', 'placement_source',
      'backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']
    const placements = rows => {
      expect(rows.every(row => fields.every(field => Object.hasOwn(row, field)))).toBe(true)
      return rows.map(row => fields.map(field => row[field]))
        .sort((a, b) => JSON.stringify(a.slice(0, 4)).localeCompare(JSON.stringify(b.slice(0, 4))))
    }
    const prove = async () => {
      const proof = await readFixture(f, 'proof')
      expect(proof.status).toBe('verified')
      expect(proof.cold_replay.authoring_equal).toBe(true)
      expect(proof.cold_replay.geometry_equal).toBe(true)
      const current = await f.checkpoint()
      for (const [field, value] of Object.entries(proof.cold_replay.authoring))
        expect(current.design[field], field).toEqual(value)
      expect(placements((await f.browser()).geometry)).toEqual(placements(proof.cold_replay.geometry))
    }
    await prove()
    await f.open(0)
    await f.change(input, 20)
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    await f.open(0)
    await f.change(input, 20)
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toHaveLength(0)
    expect(after.design.feature_log.map(e => e.id)).toEqual(before.design.feature_log.map(e => e.id))
    expect(after.design.feature_log.at(-1).children[0].params).toEqual(before.design.feature_log.at(-1).children[0].params)
    expect(after.design.helices).toEqual(before.design.helices)
    expect(after.design.strands).toEqual(before.design.strands)
    expect(adopted.geometry).not.toEqual(stored.geometry)
    await prove()
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    // Full authoring, including ordered domains, not merely deformation parameters.
    for (const field of Object.keys((await readFixture(f, 'proof')).cold_replay.authoring))
      expect((await f.checkpoint()).design[field], field).toEqual(before.design[field])
    expect(placements((await f.browser()).geometry)).toEqual(placements(stored.geometry))
    await page.evaluate(async () => (await import('/src/api/client.js')).redo())
    await prove()
    expect(placements((await f.browser()).geometry)).toEqual(placements(adopted.geometry))
    await page.evaluate(async file => (await import('/src/api/client.js')).loadDesign(file), f.file)
    await prove()
    expect(placements((await f.browser()).geometry)).toEqual(placements(adopted.geometry))
    expect(f.writes.filter(r => r.path === `${previewPath}/apply`)).toHaveLength(1)
    expect(f.writes.some(r => /\/design\/deformation(?:\/|$)/.test(r.path))).toBe(false)
  }, `${kind}-nick`)
})
