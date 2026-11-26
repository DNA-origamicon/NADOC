/** Read-only comparison of existing files, on isolated smoke servers.
 * Saves are held through page close; session cache is disabled by smoke config.
 * Only Playwright output persists. Source hashes are verified after every case.
 */
import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const sources = JSON.parse(process.env.NADOC_LOAD_COMPARISON_SOURCES || '[]')
test.skip(!sources.length, 'Requires existing source paths and an isolated workspace')
for (const source of sources) {
  test(`load comparison: ${path.basename(source)}`, async ({ page }, testInfo) => {
    test.setTimeout(150000)
    const digest = () => createHash('sha256').update(readFileSync(source)).digest('hex')
    const original = digest(), errors = trackConsoleErrors(page), times = []
    let responses = []
    page.on('response', response => {
      const url = new URL(response.url())
      if (url.pathname === '/api/design/load' || url.pathname === '/api/design/geometry') {
        responses.push({ path: url.pathname, milliseconds: response.request().timing().responseStart,
          serverTiming: response.headers()['server-timing'] })
      }
    })
    try {
      await page.goto('/?doc=__e2e__load_comparison_' + encodeURIComponent(path.basename(source, '.nadoc')))
      await page.waitForFunction(() => window.__nadocTest)
      await page.evaluate(async () => {
        const api = await import('/src/api/client.js')
        window.__loadComparisonSaveHold = api.holdFeatureEditSaves()
      })
      for (const phase of ['cold', 'warm']) {
        responses = []
        const start = Date.now()
        const info = await page.evaluate(async source => {
          const api = await import('/src/api/client.js')
          if (!await api.loadDesign(source)) throw new Error('Load failed')
          document.getElementById('welcome-screen')?.classList.add('hidden')
          const s = window.__nadocTest.store.getState()
          return { renderedBases: s.currentGeometry.length,
            loopBases: s.currentDesign.strands.reduce((n,s) => n+(s.loops||[]).reduce((n,l) => n+l.length,0),0) }
        }, source)
        await expect.poll(() => page.evaluate(() => window.__nadocTest.getDesignRenderer()
          .getBackboneEntries().length), { timeout: 30000 }).toBe(info.renderedBases)
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
        times.push({ phase, milliseconds: Date.now()-start, ...info, responses: [...responses] })
      }
      const result = { file: path.basename(source), bytes: readFileSync(source).length, sha256: original, times }
      await testInfo.attach('comparison', { body: JSON.stringify(result,null,2), contentType: 'application/json' })
      console.log('LOAD_COMPARISON '+JSON.stringify(result))
      expect(errors).toEqual([])
    } finally {
      await page.close()
      expect(digest()).toBe(original)
    }
  })
}
