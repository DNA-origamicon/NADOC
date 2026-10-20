import { test, expect } from '@playwright/test'
import { stat } from 'node:fs/promises'
import { withHistoryFixture, previewPath } from './helpers/deformation_history.js'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')

// C8 native recipes (6-helix x 84 bp and 18-helix x 504 bp, scaffolded,
// autostapled, whole-bundle Bend/Twist): parameter change -> evaluate -> new
// preview layer built (GPU raster excluded, see below). Budget p95 <= 500 ms with
// a <= 2x gate-on allowance. Opt-in diagnostics:
// NADOC_C8_SPLIT=1 (server/body/client split), NADOC_C8_PROFILE=1 (CPU profile).
for (const kind of ['bend', 'twist']) for (const large of [false, true])
test(`${kind}-${large ? 'large' : 'small'} preview Apply and Cancel latency`, async ({ page, request }) => {
  const seed = `${kind}-${large ? 'large' : 'small'}`
  const selector = kind === 'bend' ? '#def-bend-angle' : '#def-twist-value'
  test.setTimeout(240_000)
  await withHistoryFixture({ page, request }, kind, async f => {
    const source = await f.checkpoint()
    console.log(`C8 fixture ${seed} ` + JSON.stringify({ file: f.file, bytes: (await stat(f.file)).size,
      helices: source.design.helices.length, strands: source.design.strands.length }))
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    // This harness renders WebGL on the CPU (SwiftShader: ~2 s/frame at 18k nt),
    // so the viewer loop is paused and GPU raster (~1 frame on real hardware) is
    // excluded. Measured: request, transfer, parse, validation and layer build.
    const renderer = await page.evaluate(() => {
      const gl = document.createElement('canvas').getContext('webgl2'), ext = gl?.getExtension('WEBGL_debug_renderer_info')
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'unknown'
    })
    await page.evaluate(() => window.__nadocTest.pauseViewerRenderingForTest())
    const prepared = page.waitForResponse(r => new URL(r.url()).pathname === previewPath && r.request().method() === 'POST',
      { timeout: 60_000 })
    const openStart = Date.now()
    await page.locator('[title="Edit this feature"]').last().click()
    expect((await prepared).ok()).toBe(true)
    await expect(f.popup).toBeVisible({ timeout: 60_000 })
    await expect.poll(async () => (await f.display()).roots, { timeout: 30_000 }).toBe(2)
    const open = Date.now() - openStart
    const samples = [], candidateRoots = new Set()
    const evaluations = []
    const recordEvaluation = response => {
      if (new URL(response.url()).pathname === `${previewPath}/evaluate`)
        evaluations.push({ status: response.status(), sequence: response.request().postDataJSON().request_sequence })
    }
    page.on('response', recordEvaluation)
    for (const angle of [32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54]) {
      samples.push(await page.evaluate(async ({ value, selector }) => {
        const roots = () => window.__nadocTest.scene.children
          .filter(n => n.name === 'privateDeformationPreview').map(n => n.uuid).join()
        const before = roots(), input = document.querySelector(selector), t0 = performance.now()
        input.value = String(value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
        input.dispatchEvent(new Event('change', { bubbles: true }))
        await new Promise((resolve, reject) => {
          const limit = t0 + 20_000
          const tick = () => roots() !== before ? resolve()
            : performance.now() > limit ? reject(new Error('preview did not update')) : setTimeout(tick, 4)
          tick()
        })
        return performance.now() - t0
      }, { value: angle, selector }))
      await expect(page.locator('#def-apply-btn')).toBeEnabled()
      expect((await f.display()).roots).toBe(2)
      candidateRoots.add(await page.evaluate(() => window.__nadocTest.scene.children
        .find(n => n.name === 'privateDeformationPreview' && n.visible)?.uuid))
    }
    page.off('response', recordEvaluation)
    expect(evaluations).toHaveLength(samples.length)
    expect(evaluations.every(result => result.status === 200)).toBe(true)
    expect(new Set(evaluations.map(result => result.sequence)).size).toBe(samples.length)
    if (process.env.NADOC_C8_SPLIT) {
      const split = await page.evaluate(async selector => {
        const marks = {}, original = window.fetch
        window.fetch = async (...args) => {
          const url = String(args[0]?.url ?? args[0])
          if (!url.includes('/deformation-preview/evaluate')) return original(...args)
          marks.start = performance.now()
          const response = await original(...args)
          marks.headers = performance.now()
          const text = await response.clone().text()
          marks.body = performance.now(); JSON.parse(text); marks.parsed = performance.now()
          marks.bytes = text.length
          return response
        }
        const roots = () => window.__nadocTest.scene.children.filter(n => n.name === 'privateDeformationPreview').map(n => n.uuid).join()
        const before = roots(), input = document.querySelector(selector), t0 = performance.now()
        input.value = '58'; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }))
        await new Promise(r => { const tick = () => roots() !== before ? r() : setTimeout(tick, 4); tick() })
        const end = performance.now(); window.fetch = original
        return { toRequest: marks.start - t0, serverAndHeaders: marks.headers - marks.start, body: marks.body - marks.headers,
          parseOnce: marks.parsed - marks.body, afterBodyToLayer: end - marks.body, total: end - t0, bytes: marks.bytes }
      }, selector)
      console.log('C8SPLIT ' + JSON.stringify(Object.fromEntries(Object.entries(split).map(([k, v]) => [k, Math.round(v)]))))
    }
    if (process.env.NADOC_C8_PROFILE) {
      const cdp = await page.context().newCDPSession(page)
      await cdp.send('Profiler.enable'); await cdp.send('Profiler.setSamplingInterval', { interval: 200 }); await cdp.send('Profiler.start')
      await page.evaluate(async selector => {
        const roots = () => window.__nadocTest.scene.children.filter(n => n.name === 'privateDeformationPreview').map(n => n.uuid).join()
        const before = roots(), input = document.querySelector(selector)
        input.value = '60'; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }))
        await new Promise(r => { const tick = () => roots() !== before ? r() : setTimeout(tick, 4); tick() })
      }, selector)
      const { profile } = await cdp.send('Profiler.stop')
      const self = new Map(), byId = new Map(profile.nodes.map(n => [n.id, n]))
      const dt = profile.timeDeltas, counts = new Map()
      profile.samples.forEach((id, i) => counts.set(id, (counts.get(id) ?? 0) + (dt[i] ?? 0)))
      for (const [id, us] of counts) { const n = byId.get(id), key = `${n.callFrame.functionName || '(anon)'} ${n.callFrame.url.split('/').pop()}:${n.callFrame.lineNumber + 1}`; self.set(key, (self.get(key) ?? 0) + us) }
      console.log('C8PROFILE ' + JSON.stringify([...self].sort((a, b) => b[1] - a[1]).slice(0, 30).map(([k, us]) => `${Math.round(us / 1000)}ms ${k}`)))
      const inclusive = new Map(), parent = new Map()
      for (const n of profile.nodes) for (const c of n.children ?? []) parent.set(c, n.id)
      for (const [id, us] of counts) {
        const seen = new Set()
        for (let cur = id; cur !== undefined; cur = parent.get(cur)) {
          const n = byId.get(cur), key = `${n.callFrame.functionName || '(anon)'} ${n.callFrame.url.split('/').pop()}:${n.callFrame.lineNumber + 1}`
          if (seen.has(key)) continue; seen.add(key); inclusive.set(key, (inclusive.get(key) ?? 0) + us)
        }
      }
      console.log('C8INCL ' + JSON.stringify([...inclusive].sort((a, b) => b[1] - a[1]).slice(0, 45).map(([k, us]) => `${Math.round(us / 1000)}ms ${k}`)))
    }
    const sorted = [...samples].sort((a, b) => a - b)
    const p95 = sorted[Math.ceil(0.95 * sorted.length) - 1], median = sorted[Math.floor(sorted.length / 2)]
    console.log(`C8 ${seed} renderer=${renderer} open_ms=${open} candidate_buffers=${candidateRoots.size} update_ms=${samples.map(Math.round).join(',')} median=${Math.round(median)} p95=${Math.round(p95)}`)
    const beforeApply = await f.checkpoint()
    const applyStart = Date.now()
    await page.locator('#def-apply-btn').click()
    await expect(f.popup).not.toBeVisible({ timeout: 30_000 })
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    const applyMs = Date.now() - applyStart
    const committed = await f.checkpoint(), adopted = await f.browser()
    expect(committed.revision).toBe(beforeApply.revision + 1)
    expect(adopted.revision).toBe(committed.revision)
    expect(adopted.design.deformations).toEqual(committed.design.deformations)
    await f.open()
    const beforeCancel = await f.checkpoint(), stored = await f.browser()
    const canonicalReads = []
    const recordCanonicalRead = request => {
      if (request.method() === 'GET' && ['/api/design', '/api/design/geometry'].includes(new URL(request.url()).pathname))
        canonicalReads.push(request.url())
    }
    page.on('request', recordCanonicalRead)
    const writesBeforeCancel = f.writes.length, cancelStart = Date.now()
    await page.locator('#def-cancel-btn').click()
    await expect(f.popup).not.toBeVisible()
    await expect.poll(async () => (await f.display()).roots).toBe(0)
    const cancelMs = Date.now() - cancelStart
    page.off('request', recordCanonicalRead)
    expect(canonicalReads).toEqual([])
    expect(await f.checkpoint()).toEqual(beforeCancel)
    expect(await f.browser()).toEqual(stored)
    expect(f.writes.slice(writesBeforeCancel).every(r => r.path === `${previewPath}/cancel`)).toBe(true)
    console.log(`C8 ${seed} apply_ms=${applyMs} cancel_ms=${cancelMs}`)
    // Report every budget miss and still run the fixture's console checks.
    // Soft assertions fail the test; they do not relax the contract ceilings.
    expect.soft(p95, 'preview p95 including 2x allowance').toBeLessThanOrEqual(1000)
    expect.soft(applyMs, 'Apply including 2x allowance').toBeLessThanOrEqual(large ? 20000 : 6000)
    expect.soft(cancelMs, 'Cancel including 2x allowance').toBeLessThanOrEqual(400)
  }, seed, { pauseRendering: true })
})
