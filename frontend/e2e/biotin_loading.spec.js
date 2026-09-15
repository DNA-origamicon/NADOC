import { expect, test } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'

const dataDir = path.resolve('../workspace/validation/biotin_loading_20260914')

test('benchmark atomistic view switches with imported strep and matched DNA controls', async ({ page }) => {
  test.setTimeout(180000)
  execFileSync('uv', ['run', 'python', '-m', 'scripts.biotin_loading_fixtures', dataDir], { cwd: path.resolve('..') })
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__biotin_benchmark')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.metadata?.name === '__e2e__biotin_benchmark')
  const results = []
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Profiler.enable')
  for (const file of (process.env.NADOC_PROFILE_COATED ? ['coated'] : ['dna_same', 'dna_equal', 'coated'])) {
    const design = readFileSync(path.join(dataDir, `${file}.nadoc`), 'utf8')
    await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
    const loadMs = await page.evaluate(async content => {
      const start = performance.now()
      await window.__nadocTest.nanoparticles.importDesign(content)
      return performance.now()-start
    }, design)
    // Wait for the imported Full scene to paint; otherwise first-view timings
    // include unrelated Full-view shader compilation still queued by import.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    for (let repeat = 0; repeat < 3; repeat++) {
      await page.evaluate(async () => {
        await window.__nadocTest.setRepresentation('full')
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      })
      for (const mode of ['ballstick', 'vdw', 'stick']) {
        const profileThis = Boolean(process.env.NADOC_PROFILE_COATED) && file === 'coated' && repeat === 0 && mode === 'ballstick'
        if (profileThis) await cdp.send('Profiler.start')
        const result = await page.evaluate(async mode => {
          performance.clearResourceTimings()
          performance.setResourceTimingBufferSize(10000)
          const t = window.__nadocTest, start = performance.now()
          await t.setRepresentation(mode)
          const switchMs = performance.now() - start
          // An authoritative store update can supersede the request awaited by
          // setRepresentation. Measure until its replacement is actually drawn.
          do {
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
          } while (t.getAtomisticRenderer().centroidOf() === null && performance.now() - start < 10000)
          const p = t.nanoparticles.rendered()[0]
          return { mode, switchMs, requests: performance.getEntriesByType('resource').filter(r => r.startTime >= start && r.name.includes('/api/')).map(r => ({ url: r.name, ms: r.duration })), paintedMs: performance.now()-start, protein: p?.coatingAtoms ?? null,
            modeDrawn: t.getAtomisticRenderer().getMode(), dnaDrawn: t.getAtomisticRenderer().centroidOf() !== null }
        }, mode)
        if (profileThis) {
          const { profile } = await cdp.send('Profiler.stop')
          writeFileSync(path.join(dataDir, 'browser_coated.cpuprofile'), JSON.stringify(profile))
        }
        results.push({ file, repeat, loadMs, ...result })
        writeFileSync(path.join(dataDir, 'browser_after.json'), JSON.stringify(results, null, 2))
        expect(result.modeDrawn, `${file} ${repeat} ${mode}`).toBe(mode)
        expect(result.dnaDrawn, `${file} ${repeat} ${mode}: ${JSON.stringify(result.requests)}`).toBe(true)
        if (file === 'coated') {
          expect(result.protein.visible).toBe(true)
          expect(result.protein.atomCount).toBeGreaterThan(10000)
          expect(result.protein.sphereInstances).toBe(mode === 'stick' ? 0 : result.protein.atomCount)
          expect(result.protein.bondInstances).toBe(mode === 'vdw' ? 0 : result.protein.bondCount)
        }
      }
    }
  }
  writeFileSync(path.join(dataDir, 'browser_after.json'), JSON.stringify(results, null, 2))
  console.log('Biotin loading timings', JSON.stringify(results.map(({protein,...r}) => r)))
})
