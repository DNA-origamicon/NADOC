import { expect, test } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const ASSEMBLY = resolve(process.cwd(), '..', 'workspace', 'BigO-poly.nass')
test.skip(!existsSync(ASSEMBLY), 'BigO-poly assembly fixture is missing')

test('BigO-poly materializes connected inter-origami strands with full ssDNA ends', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })

  await page.goto('/?doc=__e2e__bigo-poly-topology&open=BigO-poly.nass&open-type=assembly')
  await page.waitForFunction(() => {
    const state = window.__NADOC_DBG__?.store.getState()
    return state?.assemblyActive && (state.currentAssembly?.instances?.length ?? 0) === 3
  }, null, { timeout: 90_000 })
  await page.evaluate(() => window.__NADOC_DBG__?.renderer.setAnimationLoop(null))

  const audit = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { design } = await api.flattenAssembly()
    const internal = design.strands.filter(s => s.id.startsWith('polymer::'))
    const terminal = design.strands.filter(s => s.id.startsWith('polymer-terminal::'))
    const scaffoldHelices = new Set(design.strands
      .filter(s => s.strand_type === 'scaffold')
      .flatMap(s => s.domains.map(d => d.helix_id)))
    const overhangIds = new Set(design.overhangs.map(o => o.id))
    const terminalRows = terminal.map(s => {
      const tail = s.domains.find(d => d.overhang_id)
      return {
        nucleotideCount: s.domains.reduce((n, d) => n + Math.abs(d.end_bp - d.start_bp) + 1, 0),
        sequenceCount: s.sequence?.length ?? null,
        tagged: !!tail && overhangIds.has(tail.overhang_id),
        scaffoldFree: !!tail && !scaffoldHelices.has(tail.helix_id),
      }
    })

    // Axis-site measurement at every materialized 3'→5' repeat junction. The
    // paired backbone sites are checked more precisely in the Python oracle.
    const helices = new Map(design.helices.map(h => [h.id, h]))
    const rise = 0.334
    const point = (hid, bp) => {
      const h = helices.get(hid)
      const a = [h.axis_start.x, h.axis_start.y, h.axis_start.z]
      const b = [h.axis_end.x, h.axis_end.y, h.axis_end.z]
      const v = b.map((x, i) => x - a[i])
      const norm = Math.hypot(...v) || 1
      return a.map((x, i) => x + v[i] / norm * (bp - (h.bp_start ?? 0)) * rise)
    }
    const seamDistances = design.forced_ligations
      .filter(fl => fl.id.startsWith('polymer-ligation::'))
      .map(fl => {
        const a = point(fl.three_prime_helix_id, fl.three_prime_bp)
        const b = point(fl.five_prime_helix_id, fl.five_prime_bp)
        return Math.hypot(...a.map((x, i) => x - b[i]))
      })
    return {
      internal: internal.length, terminal: terminal.length,
      forced: seamDistances.length, maxAxisSeamNm: Math.max(...seamDistances),
      terminalRows,
    }
  })

  expect(audit.internal).toBe(112)
  expect(audit.terminal).toBe(112)
  expect(audit.forced).toBe(112)
  expect(audit.maxAxisSeamNm).toBeLessThan(0.4)
  expect(new Set(audit.terminalRows.map(row => row.nucleotideCount))).toEqual(new Set([14]))
  expect(audit.terminalRows.every(row => row.sequenceCount === row.nucleotideCount)).toBe(true)
  expect(audit.terminalRows.every(row => row.tagged && row.scaffoldFree)).toBe(true)
  expect(errors).toEqual([])
})
