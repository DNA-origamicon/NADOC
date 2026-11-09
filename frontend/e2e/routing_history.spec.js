import { test, expect } from '@playwright/test'
import { withHistoryFixture, withHeldResponse } from './helpers/deformation_history.js'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')

const proof = async (request, headers) => {
  const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
  expect(response.ok()).toBe(true)
  expect((await response.json()).status).toBe('verified')
}
const placementFields = ['helix_id', 'bp_index', 'direction', 'copy_k', 'strand_id', 'strand_type',
  'domain_index', 'is_five_prime', 'is_three_prime', 'overhang_id', 'placement_source',
  'backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']
const placements = rows => JSON.stringify(rows.map(row => placementFields.map(key => row[key]))
  .sort((a, b) => JSON.stringify(a.slice(0, 4)).localeCompare(JSON.stringify(b.slice(0, 4)))))
const staples = design => design.strands.filter(s => s.strand_type === 'staple' && !s.is_reference)

test('Fine Routing step editor edits a positional resize and the part stays verified', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Expand Fine Routing', { exact: true }).last().click()
    await page.getByRole('button', { name: '✎' }).and(page.locator('[title$=" inputs"]')).last().click()
    const modal = page.getByRole('dialog', { name: 'Edit Resize strand ends', exact: true })
    await expect(modal).toBeVisible()
    // Positional (v2): the step names the strand end by helix/bp/direction, not an id.
    await expect(modal.getByLabel('Entry 1 Strand end at Base index', { exact: true })).toHaveValue('0')
    await expect(modal.getByLabel('Entry 1 Helix ID', { exact: true })).toHaveCount(0)
    await modal.getByLabel('Entry 1 Delta (bp)', { exact: true }).fill('-3')
    const edited = page.waitForResponse(r => /\/api\/design\/features\/\d+\/edit/.test(new URL(r.url()).pathname))
    await modal.getByRole('button', { name: 'Apply', exact: true }).click()
    expect((await edited).ok()).toBe(true)
    await expect(modal).not.toBeVisible()
    const { design } = await f.checkpoint()
    const child = design.feature_log.at(-1).children.at(-1)
    expect(child.params._proof_version).toBe(2)
    expect(child.params.entries[0].delta_bp).toBe(-3)
    await proof(request, f.headers)
  }, 'routing')
})

test('Autostaple offers selection-only vs entire structure and keeps unselected staples', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = (await f.checkpoint()).design
    const target = staples(before).find(s => s.domains.length >= 2)
    await page.evaluate(id => window.__nadocTest.selectRefsForTest([{ kind: 'strand', id }]), target.id)
    // Optional visual evidence (explicit opt-in directory; nothing written otherwise).
    const capture = process.env.NADOC_ROUTING_E2E_CAPTURE
    const shot = async name => { if (capture) await page.screenshot({ path: `${capture}/${name}.png` }) }
    await page.waitForTimeout(capture ? 3000 : 0)
    await shot('region-autostaple-selected')
    // Shortcut [2] is the menu item's own key binding (same click handler).
    const openAutostaple = async () => {
      await page.evaluate(() => document.activeElement?.blur())
      await page.keyboard.press('2')
      await page.getByRole('dialog', { name: 'Autostaple method', exact: true }).getByRole('button', { name: 'OK', exact: true }).click()
    }
    await openAutostaple()
    const chooser = page.getByRole('dialog', { name: 'Autostaple scope', exact: true })
    await expect(chooser).toBeVisible()
    await expect(chooser).toContainText('Selection only restaples every staple that touches the selection')
    await chooser.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(chooser).not.toBeVisible()
    expect((await f.checkpoint()).design.feature_log.length).toBe(before.feature_log.length)

    await openAutostaple()
    const done = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/full-autostaple')
    await chooser.getByRole('button', { name: 'Selection only', exact: true }).click()
    const response = await done
    expect(response.ok()).toBe(true)
    const body = response.request().postDataJSON()
    expect(body.region.length).toBeGreaterThan(0)
    await expect(page.locator('.toast-message', { hasText: 'Region autostaple complete' })).toBeVisible()
    await page.waitForTimeout(capture ? 2500 : 0)
    await shot('region-autostaple-after')
    const after = (await f.checkpoint()).design
    expect(after.feature_log.at(-1).label).toBe('Region autostaple')
    const kept = staples(before).filter(s => !s.domains.some(d => body.region.some(r =>
      r.helix_id === d.helix_id && Math.min(d.start_bp, d.end_bp) <= r.hi_bp && r.lo_bp <= Math.max(d.start_bp, d.end_bp))))
    expect(kept.length).toBeGreaterThan(0)
    for (const strand of kept) {
      const now = after.strands.find(s => s.id === strand.id)
      // Topology and assigned sequences are kept; a cleared sequence is re-derived.
      expect(now).toEqual(strand.sequence == null ? { ...strand, sequence: now.sequence } : strand)
      expect(now.sequence).toBeTruthy()
    }
    await proof(request, f.headers)
  }, 'routing')
})

const secondCrossover = '00000000-0000-0000-0000-000000006d6c'
const matrix = [
  ['strand-end-resize', [['Entry 1 Delta (bp)', '-4']]],
  ['domain-shift', [['Entry 1 Delta (bp)', '2']]],
  ['nick', [['Base index', '12']]],
  ['nick-batch', [['Nick 1 Base index', '12']]],
  ['ligate', [['Base index', '20']]],
  ['forced-ligation-create', [['Periodic seam', true]]],
  ['forced-ligation-delete', [['Forced ligation ID', 'forced-second']]],
  ['forced-ligation-delete-batch', [['Forced ligation 1 ID', 'forced-second']]],
  ['forced-ligation-extra-bases', [['Sequence', 'ACG']]],
  ['crossover-place', [['Half A Index', '28'], ['Half B Index', '28'], ['Nick A (bp)', '27'], ['Nick B (bp)', '28']]],
  ['crossover-place-batch', [['Placement 1 Half A Index', '28'], ['Placement 1 Half B Index', '28'], ['Placement 1 Nick A (bp)', '27'], ['Placement 1 Nick B (bp)', '28']]],
  ['crossover-move', [['New index', '49']]],
  ['crossover-move-batch', [['Move 1 New index', '49']]],
  ['crossover-delete', [['Crossover ID', secondCrossover]]],
  ['crossover-delete-batch', [['Crossover 1 ID', secondCrossover]]],
  ['crossover-extra-bases', [['Sequence', 'ACG']]],
  ['crossover-extra-bases-batch', [['Entry 1 Sequence', 'ACG']]],
  ['loop-skip-insert', [['Loop/skip change', '-1']]],
  ['loop-skip-twist', [['Target twist (degrees)', '-40']]],
  ['loop-skip-bend', [['Radius (nm)', '200'], ['Direction (degrees)', '90']]],
  ['loop-skip-clear', [['Helix 1 ID', design => design.helices[1].id], ['End plane (bp)', '42']]],
  ['loop-skip-clear-all', []],
]

for (const [kind, edits] of matrix) test(`Fine Routing matrix ${kind} Cancel Apply undo reopen and cold replay`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    const index = before.design.feature_log.findIndex(row => row.id === 'selected-parent')
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const expand = page.getByTitle('Expand Fine Routing', { exact: true })
      while (await expand.count()) await expand.first().click()
      await page.locator(`[data-fl-row="${index + 1}.0"]`).getByTitle(`Edit ${kind} inputs`, { exact: true }).click()
      const modal = page.getByRole('dialog').filter({ hasText: 'Edit this routing step using references' })
      await expect(modal).toBeVisible()
      const clipped = await modal.evaluate(dialog => {
        const bounds = dialog.querySelector('.modal__body').getBoundingClientRect()
        return [...dialog.querySelectorAll('input,select')].filter(input => {
          const box = input.getBoundingClientRect()
          return (input.type !== 'checkbox' && box.width < 30) || box.left < bounds.left || box.right > bounds.right
        }).map(input => input.getAttribute('aria-label'))
      })
      expect(clipped, 'Every routing field fits inside the dialog without horizontal scrolling').toEqual([])
      return modal
    }
    const change = async modal => {
      for (const [label, authored] of edits) {
        const value = typeof authored === 'function' ? authored(before.design) : authored
        const input = modal.getByLabel(label, { exact: true })
        if (typeof value === 'boolean') await input.setChecked(value)
        else if (await input.evaluate(node => node.tagName) === 'SELECT') await input.selectOption(value)
        else await input.fill(value)
      }
    }
    let modal = await open()
    await change(modal)
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    const writes = f.writes.length, cancelStart = performance.now()
    await modal.getByRole('button', { name: edits.length ? 'Cancel' : 'Close', exact: true }).last().click()
    await expect(modal).not.toBeVisible()
    const cancelMs = performance.now() - cancelStart
    expect(f.writes).toHaveLength(writes)
    expect(await f.checkpoint()).toEqual(before)
    if (!edits.length) {
      await proof(request, f.headers)
      return
    }
    modal = await open(); await change(modal)
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === `/api/design/features/${index}/edit`)
    const started = performance.now()
    await modal.getByRole('button', { name: 'Apply', exact: true }).click()
    const response = await pending
    expect(response.ok(), await response.text()).toBe(true)
    await expect(modal).not.toBeVisible()
    const applyMs = performance.now() - started
    const after = await f.checkpoint(), adopted = await f.browser()
    expect(after.revision).toBe(before.revision + 1)
    expect(adopted.revision).toBe(after.revision)
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.redo).toEqual([])
    expect(after.design.feature_log[index].children.map(row => row.id)).toEqual(['selected-child', 'later-child'])
    expect(after.design.feature_log[index].children[0].params).not.toEqual(before.design.feature_log[index].children[0].params)
    for (const offset of [1, 2]) expect(after.design.feature_log[index + offset].id).toBe(before.design.feature_log[index + offset].id)
    const cold = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect(cold.ok()).toBe(true)
    expect(await cold.json()).toMatchObject({ status: 'verified', cold_replay: { authoring_equal: true, geometry_equal: true } })
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(placements((await f.browser()).geometry) === placements(stored.geometry), 'Undo native placement parity').toBe(true)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(placements((await f.browser()).geometry) === placements(adopted.geometry), 'Reopen native placement parity').toBe(true)
    await proof(request, f.headers)
    console.log(JSON.stringify({ metric: 'routing-matrix', kind, applyMs, cancelMs, helices: before.design.helices.length }))
    expect.soft(applyMs).toBeLessThanOrEqual(6000)
    expect.soft(cancelMs).toBeLessThanOrEqual(400)
  }, `routing-matrix-${kind}`, { pauseRendering: true })
})

for (const finish of ['Cancel', 'retry']) test(`Fine Routing native downstream refusal badges and ${finish}`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Expand Fine Routing', { exact: true }).click()
    await page.getByTitle('Edit nick inputs', { exact: true }).first().click()
    const modal = page.getByRole('dialog', { name: 'Edit Nick', exact: true })
    // Moving the first nick onto the second makes the second nick unregenerable.
    await modal.getByLabel('Base index', { exact: true }).fill('9')
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/1/edit')
    await modal.getByRole('button', { name: 'Apply', exact: true }).click()
    const response = await pending
    expect(response.status()).toBe(409)
    expect((await response.json()).detail.feature_id).toBe('child-1')
    await expect(page.locator('[data-fl-row="2.1"] [data-history-status="error"]')).toHaveText('Edit failed')
    await expect(page.locator('[data-fl-row="2.2"] [data-history-status="blocked"]')).toHaveText('Blocked')
    await expect(modal.getByRole('alert')).toContainText('cannot regenerate')
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
    if (finish === 'retry') {
      await modal.getByLabel('Base index', { exact: true }).fill('6')
      await modal.getByRole('button', { name: 'Apply', exact: true }).click()
      await expect(modal).not.toBeVisible()
      expect((await f.checkpoint()).revision).toBe(before.revision + 1)
      await proof(request, f.headers)
    } else await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(page.locator('[data-history-status]')).toHaveCount(0)
    return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 409 (Conflict)'] }
  }, 'routing-refusal')
})

for (const size of ['small', 'large']) test(`Fine Routing ${size} responsiveness and retained memory`, async ({ page, request }) => {
  test.setTimeout(240_000)
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const resources = async () => (await request.get('http://127.0.0.1:8004/api/__e2e__/history/resources', { headers: f.headers })).json()
    const before = await f.checkpoint(), initial = await resources()
    const opens = [], cancels = [], localChanges = []
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const expand = page.getByTitle('Expand Fine Routing', { exact: true })
      if (await expand.count()) await expand.last().click()
      const start = performance.now()
      const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/routing-inputs'))
      await page.getByRole('button', { name: '✎' }).and(page.locator('[title$=" inputs"]')).last().click()
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      const modal = page.getByRole('dialog', { name: 'Edit Resize strand ends', exact: true })
      await expect(modal).toBeVisible()
      opens.push(performance.now() - start)
      return modal
    }
    for (let i = 0; i < 12; i++) {
      const modal = await open(), writes = f.writes.length
      const start = performance.now()
      await modal.getByLabel('Entry 1 Delta (bp)', { exact: true }).fill('-3')
      localChanges.push(performance.now() - start)
      expect(f.writes).toHaveLength(writes)
      const cancel = performance.now()
      await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
      await expect(modal).not.toBeVisible()
      cancels.push(performance.now() - cancel)
    }
    expect(await f.checkpoint()).toEqual(before)
    const modal = await open()
    await modal.getByLabel('Entry 1 Delta (bp)', { exact: true }).fill('-3')
    const start = performance.now()
    await modal.getByRole('button', { name: 'Apply', exact: true }).click()
    await expect(modal).not.toBeVisible({ timeout: 30_000 })
    const applyMs = performance.now() - start, retained = await resources()
    expect((await f.checkpoint()).revision).toBe(before.revision + 1)
    await proof(request, f.headers)
    const p95 = values => [...values].sort((a, b) => a - b)[Math.ceil(values.length * .95) - 1]
    console.log(JSON.stringify({ metric: 'routing-responsiveness', size, helices: before.design.helices.length,
      openP95: p95(opens), localChangeP95: p95(localChanges), cancelP95: p95(cancels), applyMs,
      initialRSS: initial.rss_bytes, retainedRSS: retained.rss_bytes, retainedSessions: retained.document_sessions,
      gpuRaster: 'excluded (SwiftShader)', preview: 'local modal inputs; no geometry preview' }))
    expect.soft(p95(localChanges)).toBeLessThanOrEqual(1000)
    expect.soft(p95(cancels)).toBeLessThanOrEqual(400)
    expect.soft(applyMs).toBeLessThanOrEqual(size === 'large' ? 20000 : 6000)
    expect(retained.document_sessions).toBe(0)
  }, size === 'large' ? 'routing-large' : 'routing', { pauseRendering: true })
})

test('Fine Routing batch add remove reorder keeps output identities and native replay', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), parent = before.design.feature_log.find(row => row.id === 'selected-parent')
    const [first, second] = parent.children[0].params.placements
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Expand Fine Routing', { exact: true }).click()
    await page.getByTitle('Edit crossover-place-batch inputs', { exact: true }).click()
    const modal = page.getByRole('dialog', { name: 'Edit Place crossovers', exact: true })
    await modal.getByRole('button', { name: 'Move placement 2 up', exact: true }).click()
    await modal.getByRole('button', { name: 'Remove placement 2', exact: true }).click()
    await modal.getByRole('button', { name: 'Add placement', exact: true }).click()
    for (const [side, half] of [['A', first.half_a], ['B', first.half_b]]) {
      await modal.getByLabel(`Placement 2 Half ${side} Helix ID`, { exact: true }).fill(half.helix_id)
      await modal.getByLabel(`Placement 2 Half ${side} Index`, { exact: true }).fill(String(half.index))
      await modal.getByLabel(`Placement 2 Half ${side} Direction`, { exact: true }).selectOption(half.strand)
    }
    for (const [side, value] of [['A', first.nick_bp_a], ['B', first.nick_bp_b]])
      await modal.getByLabel(`Placement 2 Nick ${side} (bp)`, { exact: true }).fill(String(value))
    await expect(modal.getByLabel('Placement 1 Output crossover ID', { exact: true })).toHaveText(second.crossover_id)
    await modal.getByRole('button', { name: 'Apply', exact: true }).click()
    await expect(modal).not.toBeVisible()
    const after = (await f.checkpoint()).design.feature_log.find(row => row.id === 'selected-parent').children[0].params.placements
    expect(after[0]).toEqual(second)
    expect(after[1].crossover_id).toBeTruthy()
    expect(after[1].crossover_id).not.toBe(first.crossover_id)
    expect(after[1].crossover_id).not.toBe(second.crossover_id)
    await proof(request, f.headers)
  }, 'routing-matrix-crossover-place-batch', { pauseRendering: true })
})

test('Fine Routing lists upstream dependents and refuses mid-log edits', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint()
    const index = before.design.feature_log.length - 1, parent = before.design.feature_log[index]
    const subIndex = parent.children.length - 1, child = parent.children[subIndex]
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const deciding = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0' && r.request().method() === 'DELETE')
    await page.getByTitle('Delete this feature', { exact: true }).first().click()
    const response = await deciding
    expect(response.ok()).toBe(true)
    const decision = await response.json()
    expect(decision.needs_cascade_decision).toBe(true)
    expect(decision.dependents.flatMap(row => row.feature_ids)).toContain(child.id)
    const modal = page.getByRole('dialog').filter({ hasText: 'Delete dependent features?' })
    await expect(modal).toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.evaluate(async () => {
      if (!await (await import('/src/api/client.js')).seekFeatures(0)) throw new Error('Seek failed')
    })
    const rolledBack = await f.checkpoint()
    await page.getByTitle('Expand Fine Routing', { exact: true }).click()
    const edit = page.getByTitle('Move the history cursor to this routing step or later to edit it.', { exact: true })
    await expect(edit).toHaveCount(parent.children.length)
    await expect(edit.first()).toBeDisabled()
    const denied = await request.post(`http://127.0.0.1:8004/api/design/features/${index}/edit?sub_index=${subIndex}`, {
      headers: f.headers, data: { params: { bp_index: 12 }, expected_design_id: rolledBack.design.id,
        expected_revision: rolledBack.revision, expected_feature_id: parent.id, expected_child_id: child.id },
    })
    expect(denied.status()).toBe(409)
    expect(await f.checkpoint()).toEqual(rolledBack)
  }, 'routing', { pauseRendering: true })
})

for (const finish of ['Cancel', 'document reset']) test(`Fine Routing delayed reference load respects ${finish}`, async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = await f.checkpoint(), stored = await f.browser()
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Expand Fine Routing', { exact: true }).click()
    await withHeldResponse(page, '/api/design/features/1/routing-inputs', async ({ ready, release }) => {
      await page.getByTitle('Edit nick inputs', { exact: true }).first().click()
      await ready
      const loading = page.getByRole('dialog').filter({ hasText: 'Loading native references' })
      await expect(loading).toBeVisible()
      if (finish === 'Cancel') await loading.getByRole('button', { name: 'Cancel', exact: true }).click()
      else await page.evaluate(() => window.dispatchEvent(new Event('nadoc:document-reset')))
      await expect(loading).not.toBeVisible()
      await release()
    })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(stored)
  }, 'routing-refusal', { pauseRendering: true })
})

test('Fine Routing large desktop visual review', async ({ page, request }, testInfo) => {
  test.skip(process.env.NADOC_ROUTING_REVIEW !== '1', 'Opt-in visual inspection in the isolated workspace')
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'bend', async f => {
    expect((await f.checkpoint()).design.helices).toHaveLength(18)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Expand Fine Routing', { exact: true }).last().click()
    await page.getByRole('button', { name: '✎' }).and(page.locator('[title$=" inputs"]')).last().click()
    const modal = page.getByRole('dialog', { name: 'Edit Resize strand ends', exact: true })
    await expect(modal).toBeVisible({ timeout: 15_000 })
    const screenshot = testInfo.outputPath('routing-large-desktop.png')
    await page.screenshot({ path: screenshot })
    console.log(`Visual review (launcher-owned output): ${screenshot}`)
    // Explicit opt-in inspection window; the outer launcher still cleans the
    // entire output root on success, failure or interruption.
    await page.waitForTimeout(30_000)
    await modal.getByRole('button', { name: 'Cancel', exact: true }).click()
    await proof(request, f.headers)
  }, 'routing-visual')
})


test('Feature log filters hide fine routing without changing recipe indices', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const before = (await f.checkpoint()).design
    const clusterIndex = before.feature_log.findIndex(entry => entry.feature_type === 'routing-cluster')
    expect(clusterIndex).toBeGreaterThanOrEqual(0)
    const row = page.locator(`[data-fl-row="${clusterIndex + 1}"]`)
    await expect(row).toBeVisible()
    await page.getByRole('button', { name: 'filter', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Fine routing', exact: true }).uncheck()
    await expect(row).toHaveCount(0)
    expect((await f.checkpoint()).design.feature_log).toEqual(before.feature_log)
    await page.getByRole('checkbox', { name: 'Fine routing', exact: true }).check()
    await expect(row).toBeVisible()
    expect((await f.checkpoint()).design.feature_log_cursor).toEqual(before.feature_log_cursor)
    await proof(request, f.headers)
  }, 'routing', { pauseRendering: true })
})


test('3D and cadnano share feature-log controls, filters, repair and loadouts', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const editor = await page.context().newPage()
    const errors = []
    editor.on('pageerror', error => errors.push(error.message))
    try {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      await editor.goto(`/cadnano-editor.html?doc=${f.doc}`)
      await editor.locator('.cn-tab-btn[data-tab="feature-log"]').click()
      const popupFits = async p => {
        const popup = await p.locator('.fl-filter-popup').boundingBox()
        const panel = await p.locator('#feature-log-panel').boundingBox()
        expect(popup.x).toBeGreaterThanOrEqual(panel.x)
        expect(popup.x + popup.width).toBeLessThanOrEqual(panel.x + panel.width)
      }
      const rows = p => p.locator('#fl-list [data-fl-row]').allTextContents()
      await expect.poll(() => rows(editor)).toEqual(await rows(page))
      for (const p of [page, editor]) {
        await expect(p.getByRole('button', { name: 'repair', exact: true })).toBeVisible()
        await expect(p.getByRole('button', { name: 'filter', exact: true })).toBeVisible()
      }
      await editor.getByRole('button', { name: 'filter', exact: true }).click()
      await popupFits(editor)
      await editor.getByRole('checkbox', { name: 'Fine routing', exact: true }).uncheck()
      await expect.poll(() => rows(page)).toEqual(await rows(editor))
      await page.getByRole('button', { name: 'filter', exact: true }).click()
      await popupFits(page)
      await expect(page.getByRole('checkbox', { name: 'Fine routing', exact: true })).not.toBeChecked()
      await page.getByRole('checkbox', { name: 'Document ops', exact: true }).check()
      await expect(editor.getByRole('checkbox', { name: 'Document ops', exact: true })).toBeChecked()
      await expect(editor.getByRole('checkbox', { name: 'Annotations and visuals' })).toBeDisabled()
      await editor.keyboard.press('Escape')
      const inspected = editor.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/repair-draft' && r.request().method() === 'GET')
      await editor.getByRole('button', { name: 'repair', exact: true }).click()
      expect((await inspected).ok()).toBe(true)
      await expect(editor.getByRole('dialog').filter({ hasText: 'Check and repair part recipe' })).toBeVisible()
      await editor.keyboard.press('Escape')
      const created = editor.waitForResponse(r => new URL(r.url()).pathname === '/api/design/loadouts' && r.request().method() === 'POST')
      await editor.getByTitle('Create loadout', { exact: true }).click()
      expect((await created).ok()).toBe(true)
      await expect.poll(() => page.getByTitle('Select loadout', { exact: true }).inputValue())
        .toBe(await editor.getByTitle('Select loadout', { exact: true }).inputValue())
      await expect.poll(() => rows(page)).toEqual(await rows(editor))
      expect(errors).toEqual([])
    } finally { await editor.close() }
  }, 'routing', { pauseRendering: true })
})


test('Cadnano edits native Fine Routing through the shared history transport', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const editor = await page.context().newPage()
    try {
      await editor.goto(`/cadnano-editor.html?doc=${f.doc}`)
      await editor.locator('.cn-tab-btn[data-tab="feature-log"]').click()
      await editor.getByTitle('Expand Fine Routing', { exact: true }).last().click()
      await editor.getByRole('button', { name: '✎' }).and(editor.locator('[title$=" inputs"]')).last().click()
      const modal = editor.getByRole('dialog', { name: 'Edit Resize strand ends', exact: true })
      await expect(modal).toBeVisible()
      await modal.getByLabel('Entry 1 Delta (bp)', { exact: true }).fill('-3')
      const edited = editor.waitForResponse(r => /\/api\/design\/features\/\d+\/edit/.test(new URL(r.url()).pathname))
      await modal.getByRole('button', { name: 'Apply', exact: true }).click()
      expect((await edited).ok()).toBe(true)
      await expect(modal).toBeHidden()
      await expect.poll(() => page.evaluate(async () => {
        const { store } = await import('/src/state/store.js')
        return store.getState().currentDesign.feature_log.at(-1).children.at(-1).params.entries[0].delta_bp
      })).toBe(-3)
      await proof(request, f.headers)
    } finally { await editor.close() }
  }, 'routing', { pauseRendering: true })
})
