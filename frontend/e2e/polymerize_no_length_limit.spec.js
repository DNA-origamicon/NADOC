/**
 * Polymerize chain length is unbounded: the old max=64 / Math.min(64) cap is
 * gone, so a count well above 64 is accepted by the input AND flows through to
 * the projected-cost preview unclamped.
 *
 * Run: cd frontend && npx playwright test e2e/polymerize_no_length_limit.spec.js \
 *        --config playwright.bench.config.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIX = resolvePath(process.cwd(), '..', 'workspace', 'bench_fixtures', 'bench_hinge_020.nass')
test.skip(!existsSync(FIX), `fixture missing: ${FIX}`)

test('polymerize accepts chain length above the old 64 cap', async ({ page }) => {
  test.setTimeout(90_000)
  page.on('pageerror', e => console.log('[pageerror] ' + e.message))
  await page.addInitScript(() => localStorage.setItem('NADOC_SHARED_RENDERER', 'true'))
  await page.goto('http://localhost:5173/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.assemblyRenderer, null, { timeout: 30_000 })

  // Load a polymerized chain (has joints between identical hinges) + enter assembly mode.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const res = await api.getLibraryFileContent('bench_fixtures/bench_hinge_020.nass')
    await api.importAssembly(res.content)
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  })
  await page.waitForFunction(
    () => (window.__NADOC_DBG__.store.getState().currentAssembly?.joints?.length ?? 0) > 0,
    null, { timeout: 30_000 },
  )

  // Open the polymerize panel and select the first seed mate from the dropdown.
  await page.evaluate(() => document.getElementById('menu-assembly-polymerize-origami')?.click())
  await page.waitForFunction(() => {
    const sel = document.getElementById('poly-mate-select')
    return sel && !sel.closest('[style*="display: none"]') && sel.options.length > 1
  }, null, { timeout: 10_000 })
  await page.evaluate(() => {
    const sel = document.getElementById('poly-mate-select')
    // option 0 is the placeholder; pick the first real joint
    sel.value = sel.options[1].value
    sel.dispatchEvent(new Event('change', { bubbles: true }))
  })

  // Type a chain length far above the retired cap of 64.
  const out = await page.evaluate(() => {
    const input = document.getElementById('poly-count')
    input.value = '200'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
    return {
      inputValue: input.value,
      inputMaxAttr: input.getAttribute('max'),
      costPreview: document.getElementById('poly-cost-preview')?.textContent ?? '',
      goDisabled: document.getElementById('poly-go-btn')?.disabled,
    }
  })
  console.log('polymerize @ 200:', JSON.stringify(out))

  // The input keeps 200 (no HTML max attr, no JS clamp).
  expect(out.inputMaxAttr, 'max attribute removed').toBeNull()
  expect(out.inputValue, 'count not clamped to 64').toBe('200')
  // The cost preview projects ~198 new instances (200 − 2), proving the
  // Math.min(64) clamp is gone from _updateCostPreview too.
  expect(out.costPreview).toMatch(/198 new instances/)
})
