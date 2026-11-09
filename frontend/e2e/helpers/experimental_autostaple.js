import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { readFile } from 'node:fs/promises'

// Inventory: guarded __e2e__ parts + autosaved project revisions in the isolated
// workspace; global-teardown removes both. Screenshots stay in testInfo.outputPath.
// The launcher's finally removes the whole owned scratch root on any failure.
test.describe('Experimental autostaple', () => {
test.skip(!process.env.NADOC_SMOKE_E2E_ROOT, 'Requires isolated smoke workspace')
const API = process.env.NADOC_E2E_API_BASE
for (const count of [6, 18]) {
  test(`${count}HB: choose Experimental, route 42 bp, and return to Standard`, async ({ page, request }, testInfo) => {
    test.setTimeout(90_000)
    const filename = path.join(process.env.NADOC_WORKSPACE, `__e2e__autostaple_${count}hb.nadoc`)
    execFileSync('uv', ['run', 'python', '-m', 'scripts.build_autostaple_review', String(count), filename],
      { cwd: path.resolve(process.cwd(), '..'), timeout: 30_000 })
    const original = JSON.parse(await readFile(filename, 'utf8'))
    const doc = `__e2e__autostaple_${count}hb`
    const headers = { 'X-NADOC-Doc': doc }
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(`/?doc=${doc}&open=${encodeURIComponent(path.basename(filename))}`)
    await expect(page.locator('#canvas')).toBeVisible()
    // Software WebGL must not monopolize the browser during dialog interactions.
    // Render actual scene frames explicitly for both visual review screenshots.
    await page.waitForFunction(() => {
      if (!window.__nadocTest) return false
      window.__nadocTest.pauseViewerRenderingForTest()
      return true
    })
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
    await expect.poll(async () => page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      return store.getState().currentDesign?.helices.length
    })).toBe(count)
    const open = async () => {
      await page.evaluate(() => document.activeElement?.blur())
      await page.keyboard.press('2')
      return page.getByRole('dialog', { name: 'Autostaple method', exact: true })
    }
    let method = await open()
    await method.getByRole('button', { name: 'Cancel', exact: true }).click()
    expect((await (await request.get(`${API}/api/design`, { headers })).json()).design.feature_log.length).toBe(original.feature_log.length)
    method = await open()
    await method.getByLabel('Method', { exact: true }).selectOption('experimental')
    await expect(method.getByLabel('Maximum staple length')).toHaveCount(0)
    await method.getByRole('button', { name: 'OK', exact: true }).click()
    const options = page.getByRole('dialog', { name: 'Experimental autostaple', exact: true })
    await expect(options.getByLabel('HC crossover repeat')).toHaveValue('42')
    await options.getByLabel('Maximum staple length').fill('42')
    await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
    await page.screenshot({ path: testInfo.outputPath('options.png') })
    const done = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/full-autostaple')
    await options.getByRole('button', { name: 'Apply', exact: true }).click()
    const response = await done
    expect(response.ok(), await response.text()).toBe(true)
    const body = await response.json()
    expect(body.full_autostaple.experimental.crossover_repeat_bp).toBe(42)
    expect(body.full_autostaple.length_limit.maximum_nt).toBe(42)
    expect(body.full_autostaple.length_limit.longest_nt).toBeLessThanOrEqual(42)
    const results = page.getByRole('dialog', { name: 'Experimental autostaple results', exact: true })
    await expect(results).toContainText('Staple lengths')
    await results.getByRole('button', { name: 'Close', exact: true }).last().click()
    await page.evaluate(() => window.__nadocTest.renderViewerFrameForTest())
    await page.screenshot({ path: testInfo.outputPath('routed.png') })
    if (process.env.NADOC_AUTOSTAPLE_REVIEW_PAUSE) {
      console.log(`AUTOSTAPLE_REVIEW ${testInfo.outputPath('routed.png')}`)
      await page.waitForTimeout(25_000)
    }
    const current = (await (await request.get(`${API}/api/design`, { headers })).json()).design
    expect(current.feature_log.at(-1).params.experimental.crossover_repeat_bp).toBe(42)
    expect(current.feature_log.at(-1).params.max_staple_length).toBe(42)
    method = await open()
    await expect(method.getByLabel('Method', { exact: true })).toHaveValue('standard')
    const standardDone = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/full-autostaple')
    await method.getByRole('button', { name: 'OK', exact: true }).click()
    const standardResponse = await standardDone
    expect(standardResponse.ok()).toBe(true)
    expect(standardResponse.request().postDataJSON()).toEqual({ scaffold_name: 'M13mp18' })
    expect((await standardResponse.json()).full_autostaple.length_limit).toBeUndefined()
    const restored = (await (await request.get(`${API}/api/design`, { headers })).json()).design
    const topology = design => design.strands.filter(s => s.strand_type === 'STAPLE')
      .map(s => JSON.stringify(s.domains.map(d => [d.helix_id, d.start_bp, d.end_bp, d.direction]))).sort()
    expect(topology(restored)).toEqual(topology(original))
    expect(errors).toEqual([])
  })
}

})
