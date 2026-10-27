import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'
import { stat } from 'node:fs/promises'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')
const previewPath = '/api/design/features/transform-preview'

test('Pose reset keeps cluster motion in the six-step example', async ({ page, request }) => {
  const { execFileSync } = await import('node:child_process')
  const { readFile } = await import('node:fs/promises')
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const file = `${f.root}/workspace/__e2e__pose-reset.nadoc`
    const expectedPath = `${f.root}/expected-reset-states.json`
    execFileSync('.venv/bin/python', ['-c', `
import json, sys
from pathlib import Path
from tools.member_motion_native_example import build
from tools.member_motion_reset_example import build as reset
from backend.api.crud import _seek_feature_log
from backend.core.design_geometry import _geometry_for_design
design = reset(build())
Path(sys.argv[1]).write_text(design.to_json())
Path(sys.argv[2]).write_text(json.dumps([_geometry_for_design(_seek_feature_log(design, i)) for i in (4, 5)]))
`, file, expectedPath], { cwd: '..', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } })
    const expected = JSON.parse(await readFile(expectedPath, 'utf8'))
    await page.evaluate(async file => {
      if (!await (await import('/src/api/client.js')).loadDesign(file)) throw Error('Load failed')
    }, file)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await expect(page.locator('#fl-list [data-fl-row="6"]')).toContainText('F6: Move/Rotate 3 [Reset base 3 pose')
    await expect(page.locator('#fl-list [data-fl-row="7"]')).toHaveCount(0)
    for (const position of [4, 5, 4, 5]) {
      const actual = await page.evaluate(async position => {
        if (!await (await import('/src/api/client.js')).seekFeatures(position)) throw Error('Seek failed')
        const s = (await import('/src/state/store.js')).store.getState()
        return { geometry: s.currentGeometry, poses: s.currentDesign.nucleotide_transforms,
          overhangs: s.currentDesign.overhangs }
      }, position)
      expect(actual.poses).toHaveLength(position === 5 ? 0 : 1)
      expect(actual.overhangs[0].label).toBe('OH1')
      expect(actual.overhangs[0].sub_domains[0].length_bp).toBe(4)
      const key = n => JSON.stringify([n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0])
      const byKey = new Map(expected[position - 4].map(n => [key(n), n]))
      expect(actual.geometry).toHaveLength(byKey.size)
      for (const n of actual.geometry) {
        const reference = byKey.get(key(n))
        expect(reference).toBeDefined()
        for (const field of ['base_position', 'backbone_position'])
          for (let axis = 0; axis < 3; axis++) expect(n[field][axis]).toBeCloseTo(reference[field][axis], 8)
      }
    }
    await page.setViewportSize({ width: 2200, height: 1200 })
    await page.screenshot({ path: '../.development-artifacts/feature-history-focus/pose-reset-f6.png' })
    await page.locator('.left-tab-btn[data-tab="scene"]').click()
    if (!await page.locator('#animation-panel-body').isVisible()) await page.locator('#animation-panel-heading').click()
    await page.locator('#anim-playpause-btn').click()
    await expect(page.locator('#anim-playpause-btn')).toHaveAttribute('title', 'Pause', { timeout: 20000 })
    await page.locator('#anim-playpause-btn').click()
    await expect(page.locator('#anim-playpause-btn')).toHaveAttribute('title', 'Play')
  }, 'unpair')
})

test('Move history edits reclassified staple addresses with exact Cancel and cold replay', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'transform', async f => {
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const d = store.getState().currentDesign.strands.find(s => s.strand_type === 'staple').domains[0]
      const transforms = [{ kind: 'base', helix_id: d.helix_id, bp_index: d.end_bp,
        direction: d.direction, copy_k: 0, compose: true, pivot: [0, 0, 0],
        translation: [2, 0, 0], rotation: [0, 0, 0, 1] }]
      const check = await api.previewNucleotideReclassification(transforms)
      if (!await api.putNucleotideTransforms(transforms, check.confirmation_token)) throw new Error('Fixture Move failed')
      if (!await api.addNick({ helixId: d.helix_id, bpIndex: Math.floor((d.start_bp + d.end_bp) / 2),
        direction: d.direction })) throw new Error('Downstream nick failed')
    })
    const source = await f.checkpoint(), before = await f.browser()
    const row = before.design.feature_log.find(r => r.op_kind === 'nucleotide-transform-batch')
    const originalTarget = row.params.transforms[0].helix_id
    const relocated = before.design.nucleotide_transforms[0].helix_id
    expect(relocated).not.toBe(originalTarget)
    const panel = page.locator('#move-rotate-panel')
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === previewPath)
      await page.getByTitle(`Edit ${row.label} parameters`, { exact: true }).click()
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      await expect(panel).toBeVisible()
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    }
    const drag = async () => {
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
      await page.evaluate(() => {
        const active = window.__nadocTest.scene.children.filter(node => node.controls?.object)
        if (active.length !== 1) throw new Error('Expected one historical residue gizmo')
        const tc = active[0].controls
        tc.dispatchEvent({ type: 'dragging-changed', value: true })
        tc.object.position.x += 1
        tc.dispatchEvent({ type: 'change' })
        tc.dispatchEvent({ type: 'dragging-changed', value: false })
      })
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      expect(response.request().postDataJSON().params.transforms[0].helix_id).toBe(originalTarget)
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    }
    await open(); await drag()
    expect(await f.checkpoint()).toEqual(source)
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(source)
    expect((await f.browser()).design).toEqual(before.design)
    await open(); await drag()
    await page.locator('#mr-apply-btn').click()
    await expect(panel).not.toBeVisible()
    const after = await f.browser()
    expect(after.design.feature_log.map(r => r.id)).toEqual(before.design.feature_log.map(r => r.id))
    expect(after.design.feature_log.find(r => r.id === row.id).params.reclassify_unpaired).toBe(true)
    expect(after.design.nucleotide_transforms[0].helix_id).toBe(relocated)
    expect(after.design.nucleotide_transforms[0].translation[0]).toBeCloseTo(3, 8)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.saveDesign(file); await api.loadDesign(file)
    }, f.file)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect((await proof.json()).status).toBe('verified')
    expect((await f.browser()).design.strands).toEqual(after.design.strands)
  }, 'unpair')
})

for (const size of ['small', 'large', 'posed-large'])
test(`Move Rotate ${size} preview Apply and Cancel latency`, async ({ page, request }) => {
  test.setTimeout(240_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const panel = page.locator('#move-rotate-panel'), source = await f.checkpoint()
    const initialGeometry = size === 'posed-large' ? (await f.browser()).geometry : null
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
    const measureNetwork = profiler || process.env.NADOC_TRANSFORM_TIMINGS
    const networkTimings = []
    const recordTiming = request => {
      if (measureNetwork && new URL(request.url()).pathname === `${previewPath}/evaluate`) {
        const t = request.timing()
        networkTimings.push({ total: t.responseEnd, wait: t.responseStart - t.requestStart,
          download: t.responseEnd - t.responseStart })
      }
    }
    page.on('requestfinished', recordTiming)
    const record = response => {
      if (new URL(response.url()).pathname === `${previewPath}/evaluate`)
        evaluations.push({ status: response.status(), sequence: response.request().postDataJSON().request_sequence })
    }
    page.on('response', record)
    const p95s = []
    // Use the same forty-sample p95 estimate for every size, including the first update.
    // Twelve samples made the reported p95 simply the maximum; no warm-up samples are discarded.
    const values = Array.from({ length: 40 }, (_, i) => 32 + i * 2)
    for (const [tool, selector] of [['move', '#mr-tx'], ['rotate', '#mr-rz']]) {
      if (tool === 'rotate') {
        // Keep each sample set within the existing 60-second preview lease.
        await page.locator('#mr-cancel-btn').click()
        await expect(panel).toBeHidden()
        await open()
      }
      const samples = []
      for (const value of values) {
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
    page.off('requestfinished', recordTiming)
    if (measureNetwork) {
      console.log('DIAGNOSTIC transform network mean ms', Object.fromEntries(
        ['total', 'wait', 'download'].map(k => [k, networkTimings.reduce((sum, t) => sum + t[k], 0) / networkTimings.length])))
      console.log('DIAGNOSTIC transform network samples ms', networkTimings.map(t =>
        [t.wait, t.download].map(Math.round)))
    }
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
    expect(evaluations).toHaveLength(values.length * 2)
    expect(evaluations.every(r => r.status === 200)).toBe(true)
    expect(new Set(evaluations.map(r => r.sequence)).size).toBe(values.length)
    expect(await f.checkpoint()).toEqual(source)
    const applyStart = Date.now()
    await page.locator('#mr-apply-btn').click()
    await expect(panel).not.toBeVisible({ timeout: 30_000 })
    const applyMs = Date.now() - applyStart, committed = await f.checkpoint()
    expect(committed.revision).toBe(source.revision + 1)
    expect((await f.browser()).revision).toBe(committed.revision)
    if (size === 'posed-large') {
      const displayed = await f.browser()
      expect(displayed.design.nucleotide_transforms).toHaveLength(18)
      const timings = await page.evaluate(async () => {
        const api = await import('/src/api/client.js')
        const { store } = await import('/src/state/store.js')
        const start = performance.now()
        if (!await api.undo()) throw Error('Undo failed')
        const undoMs = performance.now() - start
        const undone = structuredClone({ geometry: store.getState().currentGeometry,
          poses: store.getState().currentDesign.nucleotide_transforms })
        const redoStart = performance.now()
        if (!await api.redo()) throw Error('Redo failed')
        return { undoMs, redoMs: performance.now() - redoStart, undone }
      })
      expect(timings.undone.poses).toEqual(source.design.nucleotide_transforms)
      expect(timings.undone.geometry).toEqual(initialGeometry)
      expect((await f.browser()).geometry).toEqual(displayed.geometry)
      await page.evaluate(async file => {
        const api = await import('/src/api/client.js')
        await api.saveDesign(file)
        await api.undo()
      }, f.file)
      expect((await f.browser()).geometry).toEqual(timings.undone.geometry)
      await page.evaluate(async file => {
        const api = await import('/src/api/client.js')
        await api.redo(); await api.loadDesign(file)
      }, f.file)
      expect((await f.browser()).geometry).toEqual(displayed.geometry)
      const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
      expect(proof.ok()).toBe(true)
      expect((await proof.json()).status).toBe('verified')
      console.log(`C8 posed-large undo_ms=${Math.round(timings.undoMs)} redo_ms=${Math.round(timings.redoMs)}`)
      expect.soft(timings.undoMs, 'Undo display including 2x large Apply allowance').toBeLessThanOrEqual(20000)
      expect.soft(timings.redoMs, 'Redo display including 2x large Apply allowance').toBeLessThanOrEqual(20000)
    }
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
    expect.soft(applyMs, 'Apply including 2x allowance').toBeLessThanOrEqual(size.endsWith('large') ? 20000 : 6000)
    expect.soft(cancelMs, 'Cancel including 2x allowance').toBeLessThanOrEqual(400)
  }, `transform-${size}`, { pauseRendering: true })
})

for (const fixture of ['transform-owner', 'transform-single-posed'])
for (const entry of ['menu', 'shortcut'])
test(`Move Rotate ${entry} ${fixture} creation previews Cancel and creates one replayable feature`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    await expect(page.locator('#groups-panel-heading')).toContainText('Staple Groups')
    await expect(page.locator('#cluster-panel-heading')).toContainText('Movable Clusters')
    await expect(page.locator('#cluster-new-btn')).toContainText('New Cluster')
    await expect(page.locator('[data-action="organize-groups"], [data-group-create]')).toHaveCount(0)
    const panel = page.locator('#move-rotate-panel'), before = await f.checkpoint()
    const id = before.design.cluster_transforms[0].id
    const geometry = records => records.map(n => ({
      key: [n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0].join(':'),
      backbone: n.backbone_position, base: n.base_position, normal: n.base_normal,
      tangent: n.axis_tangent, slab: n.slab_position, quaternion: n.slab_quaternion,
    })).sort((a, b) => a.key.localeCompare(b.key))
    const originalGeometry = geometry((await f.browser()).geometry)
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
    expect(created.op_kind).toBe('placement-poses')
    expect(created.params.primary_cluster_id).toBe(id)
    // Server publication precedes delivery/adoption of its full geometry packet.
    await expect.poll(async () => (await f.browser()).revision).toBe(after.revision)
    const appliedGeometry = geometry((await f.browser()).geometry)
    expect(owner(after.design).translation[0]).toBe(9)
    expect(owner(after.design).rotation).not.toEqual(owner(before.design).rotation)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw new Error('Save failed')
      await api.undo()
    }, f.file)
    expect(owner((await f.checkpoint()).design)).toEqual(owner(before.design))
    expect(geometry((await f.browser()).geometry)).toEqual(originalGeometry)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect(owner((await f.checkpoint()).design)).toEqual(owner(after.design))
    expect(geometry((await f.browser()).geometry)).toEqual(appliedGeometry)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
  }, fixture)
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

for (const [code, status, message] of [
  ['preview_limit', 413, 'Injected bounded transform capacity refusal'],
  ['unsupported_transform_display', 422, 'Injected unsupported transform scope refusal'],
])
test(`Move Rotate ${code} refusal preserves the draft without blaming downstream features`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const before = await f.checkpoint(), panel = page.locator('#move-rotate-panel')
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const opened = page.waitForResponse(r => new URL(r.url()).pathname === previewPath)
    await page.getByTitle('Edit placement-poses parameters', { exact: true }).click()
    expect((await opened).ok()).toBe(true)
    await expect(panel).toBeVisible()
    const evaluated = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
    await page.locator('#mr-ja').fill('12')
    await page.locator('#mr-ja').press('Tab')
    const evaluation = await evaluated
    expect(evaluation.ok()).toBe(true)
    const draft = evaluation.request().postDataJSON().params
    expect(draft.poses).not.toEqual(before.design.feature_log.find(row => row.id === 'selected-transform').params.poses)
    await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    const browser = await f.browser(), angle = await page.locator('#mr-ja').inputValue()
    const match = url => url.pathname === `${previewPath}/apply`
    // Exercise transport/UI failure handling only. Native refusal classification
    // is covered separately; this injection is not a real capacity benchmark.
    const handler = route => route.fulfill({ status, contentType: 'application/json',
      body: JSON.stringify({ detail: { code, status: 'unverified', detail: message } }) })
    await page.route(match, handler)
    try {
      const failed = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/apply`)
      await page.locator('#mr-apply-btn').click()
      const failure = await failed
      expect(failure.status()).toBe(status)
      expect(failure.request().postDataJSON().params).toEqual(draft)
      await expect(panel).toBeVisible()
      await expect(panel).toContainText(message)
      await expect(page.locator('#mr-ja')).toHaveValue(angle)
      await expect(page.locator('[data-history-status]')).toHaveCount(0)
      expect(await f.checkpoint()).toEqual(before)
      expect(await f.browser()).toEqual(browser)
      await page.locator('#mr-cancel-btn').click()
      await expect(panel).not.toBeVisible()
      await expect(page.locator('[data-history-status]')).toHaveCount(0)
      expect(await f.checkpoint()).toEqual(before)
      expect(await f.browser()).toEqual(browser)
      return { expectedConsoleErrors: [`Failed to load resource: the server responded with a status of ${status} (${status === 413 ? 'Payload Too Large' : 'Unprocessable Entity'})`] }
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

test('Move Rotate mid-log creation refusal preserves history and Cancel restores display', async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const tip = await f.checkpoint(), panel = page.locator('#move-rotate-panel')
    const id = tip.design.feature_log.find(row => row.id === 'selected-transform').cluster_id
    await page.evaluate(async id => {
      const api = await import('/src/api/client.js')
      if (!await api.seekFeatures(1)) throw new Error('Seek failed')
      const { store } = await import('/src/state/store.js')
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      createSelectionController({ store }).replace([{ kind: 'cluster', id }])
    }, id)
    const before = await f.checkpoint(), browser = await f.browser()
    expect(before.design.feature_log_cursor).toBe(1)
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await expect(page.locator('[data-fl-row="2"]').getByTitle('Return to the latest history position before editing feature inputs.', { exact: true })).toBeDisabled()
    await page.getByRole('button', { name: 'Tools', exact: true }).hover()
    await page.locator('#menu-tools-translate-rotate').click()
    await expect(panel).toBeVisible()
    await page.locator('#mr-tx').fill('9')
    await page.locator('#mr-tx').press('Tab')
    await page.locator('#mr-rz').fill('45')
    await page.locator('#mr-rz').press('Tab')
    expect(await f.checkpoint()).toEqual(before)
    const applied = page.waitForResponse(r => new URL(r.url()).pathname === `/api/design/cluster/${id}`
      && r.request().method() === 'PATCH')
    await page.locator('#mr-apply-btn').click()
    const response = await applied
    expect(response.status()).toBe(409)
    expect((await response.json()).detail.code).toBe('historical_cursor')
    await expect(page.locator('.toast-message').filter({ hasText: 'A placement was not accepted. Unapplied movement has been retained.' })).toBeVisible()
    expect(await page.evaluate(() => window.__nadocTest.store.getState().lastError)).toEqual({
      status: 409, message: 'Return to the latest history position before editing a group.',
    })
    await expect(panel).toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).not.toBeVisible()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(browser)
    await page.evaluate(async () => {
      if (!await (await import('/src/api/client.js')).seekFeatures(-1)) throw new Error('Return to tip failed')
    })
    const restored = await f.checkpoint()
    expect(restored.design.feature_log).toEqual(tip.design.feature_log)
    await expect(page.getByTitle('Edit this move/rotate feature', { exact: true })).toBeEnabled()
    return { expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 409 (Conflict)'] }
  }, 'transform-owner')
})

test('Move Rotate upstream deletion lists the dependent transform before commit', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const before = await f.checkpoint(), browser = await f.browser()
    const selectedIndex = before.design.feature_log.findIndex(row => row.id === 'selected-transform')
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    const deciding = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/features/0'
      && r.request().method() === 'DELETE')
    await page.getByTitle('Delete this feature', { exact: true }).first().click()
    const response = await deciding
    expect(response.ok()).toBe(true)
    const decision = await response.json()
    expect(decision.needs_cascade_decision).toBe(true)
    const dependent = decision.dependents.find(row => row.feature_ids.includes('selected-transform'))
    expect(dependent?.index).toBe(selectedIndex)
    const dialog = page.getByRole('dialog').filter({ hasText: 'Delete dependent features?' })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('li')).toHaveText(decision.dependents.map(row => `F${row.index + 1}: ${row.label}`))
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(browser)
    const writes = f.writes.length
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    expect(f.writes).toHaveLength(writes)
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(browser)
    await expect(page.getByTitle('Edit this move/rotate feature', { exact: true })).toBeEnabled()
  }, 'transform-owner')
})

test('Move history scrubbing and animation reproduce each construction state', async ({ page, request }) => {
  const { execFileSync } = await import('node:child_process')
  const { readFile } = await import('node:fs/promises')
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const file = `${f.root}/workspace/__e2e__move-scrub.nadoc`
    const expectedPath = `${f.root}/expected-move-states.json`
    execFileSync('.venv/bin/python', ['-c', `
import json, sys
from pathlib import Path
from tools.member_motion_native_example import build
from backend.api import part_proof_commands as commands
from backend.core.part_history_proof import root_design
from backend.core.part_overlay_commands import command_input
from backend.core.design_geometry import _geometry_for_design
design = build()
Path(sys.argv[1]).write_text(design.to_json())
prefix = root_design(design.recipe_root)
states = []
for entry in design.feature_log:
    kind, params = command_input(entry)
    prefix = commands.execute(kind, prefix, params)
    states.append(dict(geometry=_geometry_for_design(prefix),
        poses=[p.model_dump(mode='json') for p in prefix.nucleotide_transforms]))
Path(sys.argv[2]).write_text(json.dumps(states))
`, file, expectedPath], { cwd: '..', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } })
    const expected = JSON.parse(await readFile(expectedPath, 'utf8'))
    await page.evaluate(async file => {
      if (!await (await import('/src/api/client.js')).loadDesign(file)) throw Error('Load failed')
    }, file)
    await page.setViewportSize({ width: 2200, height: 1200 })
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await expect(page.locator('#fl-list [data-fl-row="1"]')).toContainText('F1: Extrude 1 [01 Build two helices')
    await expect(page.locator('#fl-list [data-fl-row="3"]')).toContainText('F3: Move/Rotate 1')
    await expect(page.locator('#fl-list [data-fl-row="4"]')).toContainText('F4: Make Cluster 1')
    await expect(page.locator('#fl-list [data-fl-row="5"]')).toContainText('F5: Move/Rotate 2')
    await expect(page.locator('#fl-list [data-fl-row="9"]')).toContainText('F9: Make Cluster 2')
    for (const position of [0, 10, 2, 3, 4, 6, 7, 5, 1, 8, 9, 0, 10]) {
      const actual = await page.evaluate(async position => {
        const api = await import('/src/api/client.js')
        if (!await api.seekFeatures(position)) throw Error(`Seek ${position} failed`)
        return (await import('/src/state/store.js')).store.getState().currentGeometry
      }, position)
      if (position === 0) await page.screenshot({ path: '../.development-artifacts/feature-history-focus/history-scrub-first-step.png' })
      expect(actual).toHaveLength(expected[position].geometry.length)
      const key = row => JSON.stringify([row.helix_id, row.bp_index, row.direction, row.copy_k ?? 0])
      const expectedByKey = new Map(expected[position].geometry.map(row => [key(row), row]))
      for (const row of actual) {
        const reference = expectedByKey.get(key(row))
        expect(reference).toBeDefined()
        for (const field of ['backbone_position', 'base_position'])
          for (let axis = 0; axis < 3; axis++)
            expect(row[field][axis]).toBeCloseTo(reference[field][axis], 8)
      }
    }
    const overhang = await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      await api.seekFeatures(2)
      const { store } = await import('/src/state/store.js')
      const first = store.getState().currentDesign.overhangs[0]
      await api.seekFeatures(4)
      const state = store.getState()
      const grown = state.currentDesign.overhangs[0]
      return { first: { id: first.id, label: first.label, length: first.sub_domains[0].length_bp },
        grown: { id: grown.id, label: grown.label, length: grown.sub_domains[0].length_bp },
        exposed: state.currentGeometry.filter(n => n.overhang_id === grown.id).map(n => ({ bp: n.bp_index, unpaired: n.is_unpaired })) }
    })
    expect(overhang.first.label).toBe('OH1')
    expect(overhang.first.length).toBe(1)
    expect(overhang.grown).toEqual({ ...overhang.first, length: 4 })
    expect(overhang.exposed.map(n => n.bp).sort()).toEqual([0, 1, 2, 3])
    expect(overhang.exposed.every(n => n.unpaired)).toBe(true)
    await page.locator('[data-vt="overhangNames"]').click()
    expect(await page.evaluate(() => window.__nadocTest.store.getState().showOverhangNames)).toBe(true)
    await page.locator('#select-filter-trigger').click()
    await page.locator('#select-filter-menu [data-key="ovhangs"]').click()
    expect(await page.evaluate(() => window.__nadocTest.store.getState().selectableTypes.overhangs)).toBe(true)
    await page.locator('#select-filter-trigger').click()
    await expect.poll(() => page.evaluate(() => {
      const { currentHelixAxes } = window.__nadocTest.store.getState()
      const expected = Object.values(currentHelixAxes).flatMap(a => a.segments ?? [])
        .map(s => s.start.map((v, i) => (v + s.end[i]) / 2))
      const actual = []
      window.__nadocTest.scene.traverseVisible(o => {
        if (o.name === 'axisLine') actual.push(o.getWorldPosition(o.position.clone()).toArray())
      })
      return expected.length > 0 && expected.every(p => actual.some(q => Math.hypot(...p.map((v, i) => v - q[i])) < 1e-6))
    })).toBe(true)
    await page.screenshot({ path: '../.development-artifacts/feature-history-focus/move-axis-overhang-f5.png' })
    const batch = await page.evaluate(async () =>
      (await import('/src/api/client.js')).getGeometryBatch([0, 2, 3, 4, 6, 8, 9, 10]))
    for (const position of [0, 2, 3, 4, 6, 8, 9, 10])
      expect(batch[position].display_design.nucleotide_transforms).toEqual(expected[position].poses)
    await page.locator('.left-tab-btn[data-tab="scene"]').click()
    if (!await page.locator('#animation-panel-body').isVisible()) await page.locator('#animation-panel-heading').click()
    await page.locator('#anim-playpause-btn').click()
    await expect(page.locator('#anim-playpause-btn')).toHaveAttribute('title', 'Pause', { timeout: 20000 })
    await page.waitForTimeout(1000)
    await page.locator('#anim-playpause-btn').click()
    await expect(page.locator('#anim-playpause-btn')).toHaveAttribute('title', 'Play')
  }, 'unpair')
})


test('Move Rotate complete owner edit carries a prior posed insert through history', async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const before = await f.checkpoint(), original = await f.browser()
    const index = before.design.feature_log.findIndex(row => row.id === 'selected-transform')
    const entry = before.design.feature_log[index]
    const row = () => page.locator(`#fl-list [data-fl-row="${index + 1}"]`)
    const panel = page.locator('#move-rotate-panel')
    const open = async () => {
      await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
      await row().getByTitle('Edit placement-poses parameters', { exact: true }).click()
      await expect(panel).toBeVisible()
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
    }
    const move = async () => {
      const input = page.locator('#mr-tx')
      const x = Number(await input.inputValue())
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === `${previewPath}/evaluate`)
      await input.fill(String(x + 1))
      await input.press('Tab')
      const response = await pending
      expect(response.ok(), await response.text()).toBe(true)
      await expect(page.locator('#mr-apply-btn')).toBeEnabled()
      const params = response.request().postDataJSON().params
      expect(params.poses).toHaveLength(2)
      for (const pose of params.poses) {
        const old = entry.params.poses.find(p => p.cluster_id === pose.cluster_id)
        expect(pose.translation[0]).toBeCloseTo(old.translation[0] + 1, 8)
        expect(pose.translation.slice(1)).toEqual(old.translation.slice(1))
      }
      return params
    }
    await open(); await move()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(original)
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).toBeHidden()
    expect(await f.checkpoint()).toEqual(before)
    expect(await f.browser()).toEqual(original)
    await open()
    const params = await move()
    await page.locator('#mr-apply-btn').click()
    await expect(panel).toBeHidden()
    const after = await f.checkpoint(), displayed = await f.browser()
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.design.feature_log.map(row => row.id)).toEqual(before.design.feature_log.map(row => row.id))
    expect(after.design.feature_log[index].params.poses).toEqual(params.poses)
    const affected = new Set(before.design.helices.slice(0, 2).map(helix => helix.id))
    const key = n => JSON.stringify([n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0])
    const oldRows = new Map(original.geometry.map(n => [key(n), n]))
    expect(displayed.geometry).toHaveLength(oldRows.size)
    for (const value of displayed.geometry) {
      const old = oldRows.get(key(value))
      for (const field of ['base_position', 'backbone_position']) {
        const shift = affected.has(value.helix_id) ? 1 : 0
        expect(value[field][0]).toBeCloseTo(old[field][0] + shift, 8)
        expect(value[field][1]).toBeCloseTo(old[field][1], 8)
        expect(value[field][2]).toBeCloseTo(old[field][2], 8)
      }
    }
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesign(file)) throw Error('Save failed')
      if (!await api.undo()) throw Error('Undo failed: ' + JSON.stringify(window.__nadocTest.store.getState().lastError))
    }, f.file)
    expect((await f.browser()).geometry).toEqual(original.geometry)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      await api.redo(); await api.loadDesign(file)
    }, f.file)
    expect((await f.browser()).geometry).toEqual(displayed.geometry)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
  }, 'transform-posed-insert')
})

for (const organized of [false, true])
test(`Move Rotate ${organized ? 'organized placement' : 'ordinary cluster'} creation carries a posed insert in one feature`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await withHistoryFixture({ page, request }, 'transform', async f => {
    const before = await f.checkpoint(), original = await f.browser()
    const panel = page.locator('#move-rotate-panel')
    const open = async () => {
      await page.evaluate(async () => {
        const { store } = await import('/src/state/store.js')
        const { createSelectionController } = await import('/src/scene/selection_controller.js')
        createSelectionController({ store }).replace(['arm-0', 'arm-1'].map(id => ({ kind: 'cluster', id })))
        document.activeElement?.blur()
      })
      await page.getByRole('button', { name: 'Tools', exact: true }).hover()
      await page.locator('#menu-tools-translate-rotate').click()
      await expect(panel).toBeVisible()
    }
    const move = async () => {
      await page.locator('#mr-tx').fill('2')
      await page.locator('#mr-tx').press('Tab')
      await page.locator('#mr-rz').fill('35')
      await page.locator('#mr-rz').press('Tab')
    }
    await open(); await move()
    expect(await f.checkpoint()).toEqual(before)
    await page.locator('#mr-cancel-btn').click()
    await expect(panel).toBeHidden()
    expect(await f.checkpoint()).toEqual(before)
    expect((await f.browser()).geometry).toEqual(original.geometry)
    await open(); await move()
    const response = page.waitForResponse(r => new URL(r.url()).pathname === (organized ? '/api/design/group-organization/commands' : '/api/design/clusters/poses'))
    await page.locator('#mr-apply-btn').click()
    const applied = await response
    expect(applied.ok(), JSON.stringify({ response: await applied.json(), request: applied.request().postDataJSON() })).toBe(true)
    await expect(panel).toBeHidden()
    const after = await f.checkpoint(), displayed = await f.browser()
    expect(after.history).toHaveLength(before.history.length + 1)
    expect(after.design.feature_log).toHaveLength(before.design.feature_log.length + 1)
    expect(after.design.feature_log.at(-1).op_kind).toBe('placement-poses')
    expect(after.design.feature_log.at(-1).params.selected_cluster_ids).toEqual(['arm-0', 'arm-1'])
    expect(after.design.nucleotide_transforms).not.toEqual(before.design.nucleotide_transforms)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.saveDesignToWorkspace(file.split('/').at(-1))) throw Error('Save failed')
      if (!await api.undo()) throw Error('Undo failed: ' + JSON.stringify(window.__nadocTest.store.getState().lastError))
    }, f.file)
    expect((await f.browser()).geometry).toEqual(original.geometry)
    await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      if (!await api.redo()) throw Error('Redo failed')
      if (!await api.loadDesign(file)) throw Error('Reopen failed: ' + JSON.stringify(window.__nadocTest.store.getState().lastError))
    }, f.file)
    expect((await f.browser()).geometry).toEqual(displayed.geometry)
    const proof = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers: f.headers })
    expect(proof.ok()).toBe(true)
    expect((await proof.json()).status).toBe('verified')
  }, organized ? 'transform-organized-insert' : 'transform-cluster-insert')
})
