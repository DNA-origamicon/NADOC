/** Production-browser regression coverage for indexed pathview lasso paths. */
import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const API = process.env.NADOC_E2E_API_BASE ?? 'http://127.0.0.1:8002'
const FIXTURE = resolve(process.cwd(), '..', 'workspace', 'VoltronCore.nadoc')

async function lassoVisibleCanvas(page, selectFilter) {
  return page.evaluate(async filter => {
    const { editorStore } = await import('/src/cadnano-editor/store.js')
    editorStore.setState({ selectedTool: 'select', selectFilter: filter })
    const canvas = document.querySelector('#pathview-canvas')
    const rect = canvas.getBoundingClientRect()
    const capture = canvas.setPointerCapture
    const release = canvas.releasePointerCapture
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}
    const selected = new Promise((resolveSelection, reject) => {
      const channel = new BroadcastChannel('nadoc-design')
      const timer = setTimeout(() => { channel.close(); reject(new Error('selection broadcast timed out')) }, 5_000)
      channel.onmessage = event => {
        if (event.data?.type !== 'selection-changed' || !event.data?.strandIds?.length) return
        clearTimeout(timer); channel.close(); resolveSelection(event.data.strandIds)
      }
    })
    const dispatch = (type, x, y, buttons) => canvas.dispatchEvent(new PointerEvent(type, {
      button: 0, buttons, pointerId: 177,
      clientX: rect.left + x, clientY: rect.top + y,
      bubbles: true, cancelable: true,
    }))
    // Begin at the benchmark-proven empty far-right column so this arms lasso
    // rather than a domain drag, then cover the visible pathview.
    dispatch('pointerdown', canvas.width - 3, canvas.height - 3, 1)
    dispatch('pointermove', 72, 40, 1)
    dispatch('pointerup', 72, 40, 0)
    const strandIds = await selected
    canvas.setPointerCapture = capture
    canvas.releasePointerCapture = release
    return strandIds
  }, selectFilter)
}

test('indexed strand and arc lassos select real fixture geometry', async ({ page }) => {
  test.setTimeout(60_000)
  const load = await page.request.post(`${API}/api/design/import`, {
    data: { content: readFileSync(FIXTURE, 'utf8') },
  })
  expect(load.ok()).toBeTruthy()
  await page.goto('/cadnano-editor.html')
  await page.waitForFunction(() => document.querySelector('#loading-overlay')?.classList.contains('hidden'))
  await page.waitForFunction(() => document.querySelector('#pathview-canvas')?.width > 1)

  const strandIds = await lassoVisibleCanvas(page, {
    strand: true, scaf: true, stap: true, ends: true,
    xover: false, line: true, loop: false, skip: false,
  })
  expect(new Set(strandIds).size).toBeGreaterThan(10)

  const arcOwnerIds = await lassoVisibleCanvas(page, {
    strand: false, scaf: true, stap: true, ends: false,
    xover: true, line: false, loop: false, skip: false,
  })
  expect(new Set(arcOwnerIds).size).toBeGreaterThan(5)

  const design = await page.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design)
  const validIds = new Set(design.strands.map(strand => strand.id))
  expect(strandIds.every(id => validIds.has(id))).toBeTruthy()
  expect(arcOwnerIds.every(id => validIds.has(id))).toBeTruthy()
})
