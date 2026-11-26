/** Read-only load benchmark. Requires an existing source and isolated smoke workspace.
 * Saves stay held until page close; session caching is disabled by smoke config.
 * Only Playwright screenshots/attachments persist. Never copies or rewrites the source.
 */
import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const source = process.env.NADOC_LOOP_LOAD_SOURCE
test.skip(!source, 'Set NADOC_LOOP_LOAD_SOURCE to the existing loop design')
const digest = () => createHash('sha256').update(readFileSync(source)).digest('hex')

test('cold and warm loop design open preserve the source and render all loop bases', async ({ page }, testInfo) => {
  test.setTimeout(120000)
  const original = digest()
  const errors = trackConsoleErrors(page)
  const requests = []
  page.on('response', response => {
    if (new URL(response.url()).pathname.startsWith('/api/')) {
      const timing = response.request().timing()
      requests.push({ path: new URL(response.url()).pathname, status: response.status(),
        milliseconds: timing.responseStart })
    }
  })
  try {
    await page.goto('/?doc=__e2e__loop_load')
    await page.waitForFunction(() => window.__nadocTest)
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      window.__loopLoadSaveHold = api.holdFeatureEditSaves()
    })
    const times = []
    for (const phase of ['cold', 'warm']) {
      const start = Date.now()
      const expected = await page.evaluate(async path => {
        const api = await import('/src/api/client.js')
        const result = await api.loadDesign(path)
        if (!result) throw new Error('Load failed')
        document.getElementById('welcome-screen')?.classList.add('hidden')
        return window.__nadocTest.store.getState().currentDesign.strands
          .reduce((n,s) => n+(s.loops||[]).reduce((m,l) => m+l.length,0),0)
      }, source)
      expect(expected).toBeGreaterThan(0)
      await expect.poll(() => page.evaluate(() => window.__nadocTest.getDesignRenderer()
        .getBackboneEntries().filter(e => e.nuc.loop_order > 0).length), { timeout: 30000 }).toBe(expected)
      times.push({ phase, milliseconds: Date.now()-start, loopBases: expected })
    }
    await page.evaluate(() => {
      const t = window.__nadocTest
      const points = t.getDesignRenderer().getBackboneEntries().map(e => e.nuc.backbone_position)
      const lo=[0,1,2].map(i=>Math.min(...points.map(p=>p[i])))
      const hi=[0,1,2].map(i=>Math.max(...points.map(p=>p[i])))
      const center=lo.map((v,i)=>(v+hi[i])/2), size=Math.max(...hi.map((v,i)=>v-lo[i]))
      t.applyCameraPoseForTest({target:center,position:[center[0]+size*.3,center[1]-size*1.6,center[2]+size*.3],up:[0,0,1]})
    })
    await page.screenshot({ path: testInfo.outputPath('loaded-loops.png') })
    await testInfo.attach('load-times', { body: JSON.stringify(times,null,2), contentType: 'application/json' })
    console.log(JSON.stringify({times,slowRequests:requests.filter(r=>r.milliseconds>1000)}))
    expect(errors).toEqual([])
  } finally {
    await page.close()
    expect(digest()).toBe(original)
  }
})
