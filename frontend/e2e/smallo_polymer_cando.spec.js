import { expect, test } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const ASSEMBLY = resolve(process.cwd(), '..', 'workspace', 'smallO-poly.nass')
test.skip(!existsSync(ASSEMBLY), 'smallO-poly assembly fixture is missing')

test('smallO polymer runs CanDo as one continuous three-repeat bundle', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })

  await page.goto('/?doc=__e2e__smallo-poly-cando&open=smallO-poly.nass&open-type=assembly')
  await page.waitForFunction(() => {
    const state = window.__NADOC_DBG__?.store.getState()
    return state?.assemblyActive && (state.currentAssembly?.instances?.length ?? 0) === 3
  }, null, { timeout: 90_000 })
  await page.evaluate(() => window.__NADOC_DBG__?.renderer.setAnimationLoop(null))

  const jobId = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.flattenAssembly()
    const job = await api.createCandoJob({
      nonlinear: false,
      with_rmsf: true,
      with_thermal_fluctuations: true,
      autostart: true,
      design_source_path: 'smallO-poly.nass',
    })
    return job.job_id
  })

  await expect.poll(async () => page.evaluate(async id => {
    const api = await import('/src/api/client.js')
    return (await api.getCandoJob(id)).status
  }, jobId), { timeout: 120_000, intervals: [500, 1000, 2000] }).toBe('completed')

  const audit = await page.evaluate(async id => {
    const api = await import('/src/api/client.js')
    const [job, thermal] = await Promise.all([
      api.getCandoJob(id),
      api.getCandoThermalRepresentative(id),
    ])
    const bySite = new Map(thermal.representative_axis.map(row => [
      `${row.helix_id}:${row.bp_index}`, row.position,
    ]))
    const { design } = await api.flattenAssembly()
    const seamDistances = design.forced_ligations
      .filter(fl => fl.id.startsWith('polymer-ligation::'))
      .map(fl => {
        const a = bySite.get(`${fl.three_prime_helix_id}:${fl.three_prime_bp}`)
        const b = bySite.get(`${fl.five_prime_helix_id}:${fl.five_prime_bp}`)
        return Math.hypot(...a.map((x, i) => x - b[i]))
      })
    const zs = thermal.representative_axis.map(row => row.position[2])
    return {
      nNodes: job.n_nodes,
      rmsfMax: job.rmsf_max_nm,
      displayedNucleotides: thermal.representative_positions.length,
      displayedPolymerEndNucleotides: thermal.representative_positions
        .filter(row => row.helix_id.startsWith('polymer-tail::')).length,
      seamCount: seamDistances.length,
      seamMax: Math.max(...seamDistances),
      longitudinalSpan: Math.max(...zs) - Math.min(...zs),
    }
  }, jobId)

  expect(audit.nNodes).toBe(1134)
  expect(audit.rmsfMax).toBeLessThan(8)
  expect(audit.displayedNucleotides).toBe(2394)
  expect(audit.displayedPolymerEndNucleotides).toBe(126)
  expect(audit.seamCount).toBe(12)
  expect(audit.seamMax).toBeLessThan(0.5)
  expect(audit.longitudinalSpan).toBeGreaterThan(55)
  expect(audit.longitudinalSpan).toBeLessThan(70)

  // Selecting any non-native CanDo view gives the simulation exclusive ownership
  // of the viewport: the three source assembly instances must no longer remain as
  // a native overlay underneath it. Off restores those exact instances.
  await page.getByRole('button', { name: 'Simulations', exact: true }).click()
  await page.getByRole('tab', { name: 'CanDo', exact: true }).click({ timeout: 15_000 })
  const row = page.locator(`#simulate-jobs-list [data-job-id="${jobId}"]`)
  await expect(row).toBeVisible({ timeout: 15_000 })
  await row.click()
  const deform = page.locator('input[name="cando-display-mode"][value="deform"]')
  await expect(deform).toBeEnabled()
  await deform.check()
  await expect.poll(() => page.evaluate(
    () => window.__NADOC_DBG__?.assemblyRenderer.getInstanceCenters().length,
  )).toBe(0)
  const off = page.locator('input[name="cando-display-mode"][value="off"]')
  await off.check()
  await expect.poll(() => page.evaluate(
    () => window.__NADOC_DBG__?.assemblyRenderer.getInstanceCenters().length,
  )).toBe(3)
  expect(errors).toEqual([])
})
