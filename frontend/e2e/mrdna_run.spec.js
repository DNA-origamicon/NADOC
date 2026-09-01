import { expect, test } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`

async function waitForJob(page, headers, excluded, fine) {
  let job
  await expect(async () => {
    const jobs = await (await page.request.get(`${API}/mrdna/jobs`, { headers })).json()
    job = jobs.find(candidate => !excluded.has(candidate.job_id)
      && (Number(candidate.fine_steps) > 0) === fine)
    const failed = jobs.find(candidate => !excluded.has(candidate.job_id)
      && (Number(candidate.fine_steps) > 0) === fine && candidate.status === 'failed')
    expect(failed, failed?.error).toBeFalsy()
    expect(job?.status).toBe('completed')
  }).toPass({ timeout: 180_000, intervals: [500, 1000, 2000] })
  return job
}

test('mrDNA Coarse and Fine appear immediately, report centrally, and visualize', async ({ page }) => {
  test.setTimeout(300_000)
  const doc = '__e2e__mrdna-run'
  const headers = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name: 'mrdna-run' })
  const current = await (await page.request.get(`${API}/design`, { headers })).json()
  const scaffold = current.design.strands.find(s => s.strand_type === 'scaffold')
  const domain = scaffold.domains[0]
  await page.request.post(`${API}/design/strands`, { headers, data: {
    strand_type: 'staple', domains: [{ helix_id: domain.helix_id,
      start_bp: domain.end_bp, end_bp: domain.start_bp,
      direction: domain.direction === 'FORWARD' ? 'REVERSE' : 'FORWARD' }],
  } })
  const prior = await (await page.request.get(`${API}/mrdna/jobs`, { headers })).json()
  const excluded = new Set(prior.map(job => job.job_id))

  await page.getByRole('button', { name: 'Simulations', exact: true }).click()
  await page.getByRole('tab', { name: 'mrDNA', exact: true }).click()
  await page.locator('#mrdna-jobs-adv-toggle').click()
  await page.locator('#mrdna-jobs-coarse-steps').fill('1000')

  for (const [button, fine] of [['#mrdna-jobs-coarse-btn', false], ['#mrdna-jobs-fine-btn', true]]) {
    await page.locator(button).click()
    await expect(page.locator('#simulate-jobs-list [data-job-id]').first()).toBeVisible({ timeout: 1_000 })
    await expect(page.locator('#simulate-jobs-status')).toContainText(/mrDNA.*preparing/i, { timeout: 3_000 })
    const job = await waitForJob(page, headers, excluded, fine)
    excluded.add(job.job_id)
    const row = page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`)
    await expect(row).toBeVisible({ timeout: 15_000 })
    await row.click()
    const deform = page.locator('input[name="mrdna-display-mode"][value="deform"]')
    await expect(deform).toBeEnabled({ timeout: 15_000 })
    await deform.check()
    await expect(deform).toBeChecked()
    await page.locator('input[name="mrdna-display-mode"][value="off"]').check()
  }

  await expect(page.locator('#mrdna-jobs-progress')).toHaveCount(0)
  await expect(page.locator('#mrdna-jobs-detail-status')).toHaveCount(0)
})
