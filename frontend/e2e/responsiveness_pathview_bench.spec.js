/**
 * Measured redraw benchmark for the caDNAno path editor.
 *
 * This is a campaign benchmark, not a timing gate: it writes raw samples to the
 * Playwright attachment log and stdout so before/after runs can be compared on
 * the same machine.  The fixture is loaded into Playwright's throwaway backend,
 * then expanded only in the browser's editor store; no design file is changed.
 *
 * Run:
 *   NADOC_PERF_FACTOR=12 npx playwright test \
 *     e2e/responsiveness_pathview_bench.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const API = process.env.NADOC_E2E_API_BASE ?? 'http://127.0.0.1:8002'
const FIXTURE = resolve(process.cwd(), '..', 'workspace', 'VoltronCore.nadoc')
const FACTOR = Math.max(1, Number(process.env.NADOC_PERF_FACTOR ?? 12))
const SAMPLES = Math.max(5, Number(process.env.NADOC_PERF_SAMPLES ?? 25))

function summary(values) {
  const sorted = [...values].sort((a, b) => a - b)
  const percentile = p => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))]
  return {
    n: sorted.length,
    medianMs: percentile(0.5),
    p95Ms: percentile(0.95),
    minMs: sorted[0],
    maxMs: sorted.at(-1),
    meanMs: sorted.reduce((a, b) => a + b, 0) / sorted.length,
  }
}

test('pathview redraw and design-update responsiveness', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  const fixtureText = readFileSync(FIXTURE, 'utf8')
  const load = await page.request.post(`${API}/api/design/import`, {
    data: { content: fixtureText },
  })
  expect(load.ok(), `fixture import failed: ${load.status()}`).toBeTruthy()

  const browserErrors = []
  page.on('pageerror', err => browserErrors.push(err.message))
  page.on('console', msg => {
    if (msg.type() === 'error') browserErrors.push(msg.text())
  })
  await page.goto('/cadnano-editor.html')
  await page.waitForFunction(() => document.querySelector('#loading-overlay')?.classList.contains('hidden'))
  await page.waitForFunction(() => document.querySelector('#pathview-canvas')?.width > 1)

  const report = await page.evaluate(async ({ factor, samples }) => {
    const { editorStore } = await import('/src/cadnano-editor/store.js')
    const base = structuredClone(editorStore.getState().design)
    if (!base?.strands?.length) throw new Error('editor design did not load')

    // Expand topology without changing geometry/layout. Repeated strands and
    // crossovers overlap visually but exercise the same real drawing paths as a
    // larger design, with stable counts and no backend/file mutation.
    const expanded = structuredClone(base)
    expanded.strands = Array.from({ length: factor }, (_, copy) =>
      base.strands.map(s => ({ ...structuredClone(s), id: `${s.id}__perf${copy}` }))).flat()
    expanded.crossovers = Array.from({ length: factor }, (_, copy) =>
      (base.crossovers ?? []).map(x => ({ ...structuredClone(x), id: `${x.id ?? 'xo'}__perf${copy}` }))).flat()
    expanded.extensions = Array.from({ length: factor }, (_, copy) =>
      (base.extensions ?? []).map(x => ({ ...structuredClone(x), id: `${x.id ?? 'ext'}__perf${copy}`,
        strand_id: `${x.strand_id}__perf${copy}` }))).flat()

    const canvas = document.querySelector('#pathview-canvas')
    const canvasDigest = () => {
      const image = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height)
      const pixels = new Uint32Array(image.data.buffer)
      let hash = 2166136261
      let transitions = 0
      for (let i = 0; i < pixels.length; i++) {
        hash = Math.imul(hash ^ pixels[i], 16777619)
        if (i && pixels[i] !== pixels[i - 1]) transitions++
      }
      return { fnv32: (hash >>> 0).toString(16).padStart(8, '0'), transitions,
        width: canvas.width, height: canvas.height }
    }
    const dispatchWheel = deltaY => {
      const t0 = performance.now()
      canvas.dispatchEvent(new WheelEvent('wheel', {
        deltaY, offsetX: canvas.width / 2, offsetY: canvas.height / 2,
        clientX: canvas.width / 2, clientY: canvas.height / 2,
        bubbles: true, cancelable: true,
      }))
      return performance.now() - t0
    }
    const runWheel = () => {
      const out = []
      for (let i = 0; i < samples; i++) out.push(dispatchWheel(i % 2 ? 1 : -1))
      return out
    }
    const setTools = patch => {
      const cur = editorStore.getState().viewTools
      editorStore.setState({ viewTools: { ...cur, ...patch } })
    }
    const dispatchPointer = (x, y) => {
      const rect = canvas.getBoundingClientRect()
      const t0 = performance.now()
      canvas.dispatchEvent(new PointerEvent('pointermove', {
        clientX: rect.left + x, clientY: rect.top + y,
        bubbles: true, cancelable: true, pointerId: 91,
      }))
      return performance.now() - t0
    }

    const updateSamples = []
    for (let i = 0; i < Math.max(5, Math.floor(samples / 2)); i++) {
      const next = { ...expanded, metadata: { ...expanded.metadata, __perfTick: i } }
      const t0 = performance.now()
      editorStore.setState({ design: next })
      updateSamples.push(performance.now() - t0)
    }

    // Disable crossover hover so this isolates domain hit-testing. Find one
    // rendered track, then probe an empty bp column on that same track; the
    // legacy implementation scans every strand/domain before returning null.
    const currentFilter = editorStore.getState().selectFilter
    editorStore.setState({ selectFilter: { ...currentFilter, xover: false } })
    let hoverTrackY = null
    for (let y = 32; y < canvas.height - 8; y += 2) {
      dispatchPointer(Math.min(240, canvas.width / 3), y)
      if (editorStore.getState().hoveredStrand) { hoverTrackY = y; break }
    }
    if (hoverTrackY == null) throw new Error('could not locate a pathview track for hover benchmark')
    const hoverHitTest = []
    for (let i = 0; i < samples; i++) {
      const start = performance.now()
      for (let event = 0; event < 100; event++) {
        dispatchPointer(canvas.width - 3 - (event % 2), hoverTrackY)
      }
      hoverHitTest.push(performance.now() - start)
    }
    const hoverEvidence = {
      trackY: hoverTrackY,
      finalHoveredStrand: editorStore.getState().hoveredStrand?.strandId ?? null,
    }

    // Twenty pointer moves model one high-rate pan burst. Record both time spent
    // synchronously dispatching events and time through the next painted frame.
    const panDispatch = []
    const panPaint = []
    const panSamples = Math.max(5, Math.floor(samples / 6))
    const rect = canvas.getBoundingClientRect()
    const panX = canvas.width / 2
    const panY = canvas.height / 2
    // Synthetic PointerEvents are not registered as active pointers by Chromium,
    // so pointer capture would throw even though the editor's pan logic is valid.
    // Capture is irrelevant while all benchmark events target the same canvas.
    const setPointerCapture = canvas.setPointerCapture
    const releasePointerCapture = canvas.releasePointerCapture
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}
    canvas.dispatchEvent(new PointerEvent('pointerdown', {
      button: 1, buttons: 4, pointerId: 92,
      clientX: rect.left + panX, clientY: rect.top + panY,
      bubbles: true, cancelable: true,
    }))
    for (let sample = 0; sample < panSamples; sample++) {
      const start = performance.now()
      for (let event = 0; event < 20; event++) {
        const dx = event === 19 ? 0 : ((event % 7) - 3) * 4
        canvas.dispatchEvent(new PointerEvent('pointermove', {
          buttons: 4, pointerId: 92,
          clientX: rect.left + panX + dx, clientY: rect.top + panY,
          bubbles: true, cancelable: true,
        }))
      }
      panDispatch.push(performance.now() - start)
      await new Promise(requestAnimationFrame)
      panPaint.push(performance.now() - start)
    }
    canvas.dispatchEvent(new PointerEvent('pointerup', {
      button: 1, pointerId: 92,
      clientX: rect.left + panX, clientY: rect.top + panY,
      bubbles: true, cancelable: true,
    }))
    canvas.setPointerCapture = setPointerCapture
    canvas.releasePointerCapture = releasePointerCapture
    hoverEvidence.panFinalCanvas = canvasDigest()

    setTools({ lengthHeatmap: false, sequences: false, undefinedBases: false,
      overhangNames: false, periodicBoundary: false, grid: true })
    const plain = runWheel()
    const evidence = { plain: canvasDigest() }
    setTools({ lengthHeatmap: true })
    const heatmap = runWheel()
    setTools({ lengthHeatmap: false, sequences: true })
    const sequences = runWheel()
    setTools({ sequences: false, undefinedBases: true })
    const undefinedBases = runWheel()
    setTools({ undefinedBases: false, overhangNames: true })
    const overhangNames = runWheel()
    evidence.overhangNames = canvasDigest()
    setTools({ overhangNames: false, periodicBoundary: true })
    const periodic = runWheel()
    evidence.periodic = canvasDigest()
    setTools({ periodicBoundary: false })
    // Zoom far enough that only a small bp/helix window is visible. This is the
    // editing regime where viewport culling should avoid traversing the rest of
    // a large design while a user pans, zooms, or drags an endpoint.
    for (let i = 0; i < 18; i++) dispatchWheel(-1)
    const zoomedPlain = runWheel()
    evidence.zoomedPlain = canvasDigest()
    setTools({ periodicBoundary: true })
    const zoomedPeriodic = runWheel()
    evidence.zoomedPeriodic = canvasDigest()
    setTools({ periodicBoundary: false })
    // Exercise the whole-strand glow path used during ordinary select/edit
    // work. Broadcast through the same cross-window API as the 3D view.
    const { getDocId } = await import('/src/shared/doc_id.js')
    const perfChannel = new BroadcastChannel('nadoc-design')
    perfChannel.postMessage({ type: 'selection-changed', source: '__perf_sender__',
      docId: getDocId(), strandIds: [expanded.strands[0].id] })
    await new Promise(resolve => setTimeout(resolve, 25))
    perfChannel.close()
    const selectedZoomed = runWheel()
    evidence.selectedZoomed = canvasDigest()

    return {
      fixture: {
        factor,
        helices: expanded.helices.length,
        strands: expanded.strands.length,
        domains: expanded.strands.reduce((n, s) => n + (s.domains?.length ?? 0), 0),
        crossovers: expanded.crossovers.length,
        hoverEventsPerSample: 100,
      },
      raw: { designUpdate: updateSamples, plain, heatmap, sequences, undefinedBases,
        overhangNames, periodic, zoomedPlain, zoomedPeriodic, selectedZoomed, hoverHitTest,
        panDispatch, panPaint },
      canvasEvidence: evidence,
      hoverEvidence,
    }
  }, { factor: FACTOR, samples: SAMPLES })

  report.summary = Object.fromEntries(
    Object.entries(report.raw).map(([name, values]) => [name, summary(values)]),
  )
  report.browserErrors = browserErrors
  console.log(`[pathview benchmark] ${JSON.stringify(report)}`)
  await testInfo.attach('pathview-responsiveness.json', {
    body: JSON.stringify(report, null, 2),
    contentType: 'application/json',
  })
  if (process.env.NADOC_PERF_OUTPUT) {
    const output = resolve(process.cwd(), process.env.NADOC_PERF_OUTPUT)
    mkdirSync(resolve(output, '..'), { recursive: true })
    writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
  }

  expect(report.fixture.strands).toBeGreaterThan(2_000)
  expect(report.fixture.crossovers).toBeGreaterThan(6_000)
  expect(browserErrors).toEqual([])
  for (const metric of Object.values(report.summary)) {
    expect(Number.isFinite(metric.medianMs)).toBe(true)
    expect(metric.n).toBeGreaterThanOrEqual(5)
  }
})
