/**
 * production_wizard.spec.js — TROUBLESHOOTING/verification spec for "select a finished
 * relaxation, press ＋ New job, and the wizard opens on Production seeded from THAT run".
 *
 * Not part of the routine dev cycle. It exists because the claim is only observable in the
 * real app: the wizard's production pane is driven end-to-end by `POST /md/protocol-plan`
 * against a REAL package (its manifest, its PSF atom count, its equilibrated checkpoint),
 * and none of that exists in a unit test — `md_job_wizard_model.test.js` pins the shaping,
 * this pins that the shaping is fed the right thing.
 *
 * Read-only: opens an existing design through the app's own library and clicks an existing
 * finished job. It opens the wizard and CANCELS. Nothing is submitted, stopped, deleted or
 * archived, and no .nadoc is written (memory/feedback_no_live_server_mutation_for_verify).
 *
 * Runs against the USER'S dev servers (playwright.livedev.config.js), booting on a PINNED
 * ?doc so the default document is untouched.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/production_wizard.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'

const SHOTS = 'e2e/screenshots'

// A design with a COMPLETED NAMD relaxation on this machine. Its relaxation is archived
// (the package lives on the archive drive), which is exactly the case that used to make
// production mode unreachable — so it is the right fixture, not a compromise.
const DESIGN = '2hb_1-0xT'

async function openDesign(page, doc, design) {
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  const needsPick = await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)
  if (needsPick) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${design}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
  await page.waitForTimeout(1500)
}

async function openNamdPanel(page) {
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click({ timeout: 15_000 })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click({ timeout: 15_000 })
  await page.waitForTimeout(1200)
}

/** The unified Simulate list is the ONE list the user clicks. */
const listRows = (page) => page.locator('#simulate-jobs-list [data-job-id]')

/** Select the first COMPLETED row of the given kind — the gesture the feature keys off.
 *  `kind` is 'relaxation' (an independent sample) or 'production' (a continuation). */
async function selectCompleted(page, kind = 'relaxation') {
  const rows = listRows(page)
  await rows.first().waitFor({ state: 'visible', timeout: 30_000 })
  const n = await rows.count()
  for (let i = 0; i < n; i++) {
    const row = rows.nth(i)
    const id = await row.getAttribute('data-job-id')
    const ok = await page.evaluate(async ([jobId, want]) => {
      const r = await fetch(`/api/md/jobs`, { headers: { 'X-NADOC-Doc': 'prod-wizard' } })
      const jobs = await r.json()
      const j = jobs.find(x => x.job_id === jobId)
      if (!j || j.status !== 'completed') return false
      return want === 'production' ? j.run_kind === 'production' : j.run_kind !== 'production'
    }, [id, kind])
    if (ok) { await row.click(); await page.waitForTimeout(800); return id }
  }
  throw new Error(`no completed ${kind} in the list on this machine`)
}

const selectARelaxation = (page) => selectCompleted(page, 'relaxation')

/** The wizard now opens on step 1 ("Where it runs"). Local is preselected and always
 *  ready, so every existing assertion about the protocol form just needs the step
 *  advanced first. */
async function openSettingsTab(modal) {
  await modal.locator('.wizard-tab', { hasText: 'Protocol & settings' }).click()
}

test.describe('New job on a finished relaxation opens Production, seeded from it', () => {
  test('the wizard lands on Production with that run as the parent', async ({ page }) => {
    await openDesign(page, 'prod-wizard', DESIGN)
    await openNamdPanel(page)
    const parentId = await selectARelaxation(page)

    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
    const modal = page.locator('.modal--wizard')
    await expect(modal).toBeVisible({ timeout: 20_000 })
    await openSettingsTab(modal)

    // Production, not the blank relaxation form the button used to always open.
    await expect(modal.locator('.wizard-mode.is-selected .wizard-mode__label'))
      .toHaveText('Production')

    // …and seeded from the run that was SELECTED, not from the newest one for the part.
    const picked = await modal.locator('.wizard-scope--parent select').inputValue()
    expect(picked).toBe(parentId)

    // The plan has to have landed: no error banner, and a stage table.
    await expect(modal.locator('.wizard-status')).toHaveText('', { timeout: 30_000 })
    await modal.screenshot({ path: `${SHOTS}/production-wizard-1-setup.png` })
  })

  test('every production setting is a real control with a provenance chip', async ({ page }) => {
    await openDesign(page, 'prod-wizard', DESIGN)
    await openNamdPanel(page)
    await selectARelaxation(page)
    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
    const modal = page.locator('.modal--wizard')
    await expect(modal).toBeVisible({ timeout: 20_000 })
    await openSettingsTab(modal)
    await expect(modal.locator('.wizard-status')).toHaveText('', { timeout: 30_000 })

    // The controls that did not exist before: GPU-resident, the two integrator axes, the
    // seed. Plus the ones that did, now carrying chips.
    const labels = await modal.locator('.wizard-fields .wizard-field__label')
      .allTextContents()
    for (const want of ['Run length', 'Trajectory interval', 'Restraints',
                        'Langevin coupling', 'Random seed', 'Timestep',
                        'Rigid bonds', 'H-mass repartitioning (HMR)', 'GPU-resident mode']) {
      expect(labels.some(l => l.includes(want)), `missing control: ${want}`).toBe(true)
    }
    // Every control says where its value came from — the whole promise of the wizard.
    const fields = modal.locator('.wizard-fields .wizard-field')
    expect(await fields.count()).toBe(await modal.locator('.wizard-chip').count() + 1)

    // What the run inherits rather than chooses, stated.
    await expect(modal.locator('.wizard-inherited')).toBeVisible()
    const inherited = await modal.locator('.wizard-inherited__label').allTextContents()
    expect(inherited).toContain('Continuing from')
    expect(inherited).toContain('Cell')
    await modal.screenshot({ path: `${SHOTS}/production-wizard-2-settings.png` })
  })

  test('tab 2 shows the last relaxation stage beside the production stages', async ({ page }) => {
    await openDesign(page, 'prod-wizard', DESIGN)
    await openNamdPanel(page)
    await selectARelaxation(page)
    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
    const modal = page.locator('.modal--wizard')
    await expect(modal).toBeVisible({ timeout: 20_000 })
    await openSettingsTab(modal)
    await expect(modal.locator('.wizard-status')).toHaveText('', { timeout: 30_000 })

    await modal.locator('.wizard-tab', { hasText: 'What each stage runs' }).click()
    const table = modal.locator('.wizard-stages table')
    await expect(table).toBeVisible({ timeout: 20_000 })

    // Three columns: the relaxation being continued, the reseed bridge, the production run.
    const heads = await table.locator('thead th').allTextContents()
    expect(heads[0]).toContain('Parameter')
    expect(heads[1]).toContain('Relaxation')
    expect(heads.length).toBe(4)

    // Differences from the relaxation are highlighted — the timestep and the thermostat
    // coupling always move, so the highlight is never vacuously empty.
    const changed = modal.locator('.wizard-cell--changed')
    expect(await changed.count()).toBeGreaterThan(0)

    // The relaxation column is read-only; the production one is not.
    await expect(modal.locator('td.wizard-cell--reference').first())
      .toHaveClass(/wizard-cell--locked/)
    await modal.screenshot({ path: `${SHOTS}/production-wizard-3-stages.png` })
  })

  test('a production stage parameter can be edited by hand', async ({ page }) => {
    await openDesign(page, 'prod-wizard', DESIGN)
    await openNamdPanel(page)
    await selectARelaxation(page)
    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
    const modal = page.locator('.modal--wizard')
    await expect(modal).toBeVisible({ timeout: 20_000 })
    await openSettingsTab(modal)
    await expect(modal.locator('.wizard-status')).toHaveText('', { timeout: 30_000 })
    await modal.locator('.wizard-tab', { hasText: 'What each stage runs' }).click()
    await expect(modal.locator('.wizard-stages table')).toBeVisible({ timeout: 20_000 })

    // The production column's Langevin damping cell — editable, unlike the relaxation
    // reference column beside it.
    const row = modal.locator('tr', { has: page.locator('th.param', { hasText: /Langevin damping/ }) })
    const cell = row.locator('td').last()
    await cell.click()
    await cell.locator('input').fill('3.5')
    await cell.locator('input').press('Enter')
    await expect(modal.locator('.wizard-override-summary')).toBeVisible({ timeout: 30_000 })
    await expect(row.locator('td').last()).toHaveClass(/wizard-cell--overridden/)
    await modal.screenshot({ path: `${SHOTS}/production-wizard-4-edited.png` })

    // Undo puts it back — a hand edit is on the same stack as everything else.
    await modal.locator('.wizard-tabbar button', { hasText: 'Undo' }).click()
    await expect(modal.locator('.wizard-override-summary')).toBeHidden({ timeout: 30_000 })
  })

  test('the undersized-cell override unblocks Create, from the condition itself', async ({ page }) => {
    // The one BLOCKING condition a production plan can carry: a cell sized for the short
    // restrained ladder is too small for a long free run. Create is refused until the
    // override next to the condition is accepted — and the override has to reach the
    // plan, or the button would stay dead with nothing left to click.
    await openDesign(page, 'prod-wizard', DESIGN)
    await openNamdPanel(page)
    await selectARelaxation(page)
    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
    const modal = page.locator('.modal--wizard')
    await expect(modal).toBeVisible({ timeout: 20_000 })
    await openSettingsTab(modal)
    await expect(modal.locator('.wizard-status')).toHaveText('', { timeout: 30_000 })
    await modal.locator('.wizard-tab', { hasText: 'What each stage runs' }).click()

    const create = modal.getByRole('button', { name: 'Create job' })
    const override = modal.locator('.wizard-override input[type="checkbox"]')
    if (!(await override.count())) return          // this package's cell is big enough
    await expect(create).toBeDisabled()
    await override.check()
    await expect(create).toBeEnabled({ timeout: 30_000 })
  })

  // ── Chaining: a completed PRODUCTION as the parent ────────────────────────
  //
  // The backend has always chained; only the UI had no way to ask. What matters visually
  // is that the screen says which of the two things is happening — off a relaxation the
  // child is an independent sample, off a production it EXTENDS one trajectory, and
  // mistaking the second for the first double-counts the statistics.

  test('a selected production run opens the wizard as a CONTINUATION', async ({ page }) => {
    await openDesign(page, 'prod-wizard', DESIGN)
    await openNamdPanel(page)
    const parentId = await selectCompleted(page, 'production')

    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
    const modal = page.locator('.modal--wizard')
    await expect(modal).toBeVisible({ timeout: 20_000 })
    await openSettingsTab(modal)
    await expect(modal.locator('.wizard-mode.is-selected .wizard-mode__label'))
      .toHaveText('Production')
    expect(await modal.locator('.wizard-scope--parent select').inputValue()).toBe(parentId)
    await expect(modal.locator('.wizard-status')).toHaveText('', { timeout: 30_000 })

    // The one sentence that must not be missed, and it is styled to be read.
    const help = modal.locator('.wizard-field__help--strong')
    await expect(help).toBeVisible()
    await expect(help).toContainText('EXTENDS')
    await expect(help).toContainText('correlated')

    // The picker says which kind each option is — they used to read as duplicates.
    const options = await modal.locator('.wizard-scope--parent select option')
      .allTextContents()
    expect(options.some(o => /production run created/.test(o))).toBe(true)
    expect(options.some(o => /relaxation created/.test(o))).toBe(true)

    // And what is inherited is chain-aware.
    const inherited = await modal.locator('.wizard-inherited__label').allTextContents()
    expect(inherited).toContain('Position in the chain')
    expect(inherited).toContain('Already simulated')
    await expect(modal.locator('.wizard-inherited > summary'))
      .toHaveText('Inherited from the run being extended')
    await modal.screenshot({ path: `${SHOTS}/production-wizard-6-chained.png` })
  })

  test('tab 2 heads the reference column by what it IS, not "Relaxation"', async ({ page }) => {
    await openDesign(page, 'prod-wizard', DESIGN)
    await openNamdPanel(page)
    await selectCompleted(page, 'production')
    await page.locator('#md-jobs-new-btn').click({ timeout: 15_000 })
    const modal = page.locator('.modal--wizard')
    await expect(modal).toBeVisible({ timeout: 20_000 })
    await openSettingsTab(modal)
    await expect(modal.locator('.wizard-status')).toHaveText('', { timeout: 30_000 })
    await modal.locator('.wizard-tab', { hasText: 'What each stage runs' }).click()
    await expect(modal.locator('.wizard-stages table')).toBeVisible({ timeout: 20_000 })

    const heads = await modal.locator('.wizard-stages thead th').allTextContents()
    expect(heads[1]).toContain('Continuing')
    expect(heads[1]).not.toContain('Relaxation')
    // Both columns are productions, so the ladder-vs-production note box is gone.
    await expect(modal.locator('.wizard-note')).toHaveCount(0)
    // The bridge carries velocities forward instead of redrawing them: the reseed column
    // has no `reinitvels` row value, and its own step count is zero.
    const reseed = modal.locator('.wizard-stages tbody tr td:nth-of-type(2)')
    expect((await reseed.allTextContents()).some(t => t.trim() === '0')).toBe(true)
    await modal.screenshot({ path: `${SHOTS}/production-wizard-7-chained-stages.png` })
  })

  test.afterEach(async ({ page }) => {
    // Read-only: leave without creating anything.
    const cancel = page.locator('.modal--wizard').getByRole('button', { name: 'Cancel' })
    if (await cancel.isVisible().catch(() => false)) await cancel.click()
  })
})
