/**
 * Job Wizard — exercise the real modal against the user's running dev servers.
 *
 * READ-ONLY by construction (see memory/feedback_no_live_server_mutation_for_verify.md):
 * boots on a pinned document, and NEVER clicks Create / Create & run, so no job is ever
 * submitted, stopped, deleted or archived. It only opens the wizard and reads what the
 * plan endpoint renders.
 *
 * Run:
 *   cd frontend
 *   npx playwright test --config playwright.livedev.config.js e2e/md_job_wizard.spec.js
 */
import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api'
const DESIGN_PATH = '/home/joshua/NADOC/Examples/26hb_platform_v3.nadoc'
const DOC = 'wizard-exercise'

async function openDynamics(page) {
  await page.goto(`/?doc=${DOC}`)
  await page.waitForSelector('#canvas')
  await page.evaluate(() => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.querySelectorAll('.left-tab-btn').forEach(b => { b.disabled = false })
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    document.querySelectorAll('.tab-content').forEach(el => {
      el.hidden = el.id !== 'tab-content-dynamics'
    })
  })
  // The Simulate section fronts every engine's panel behind one segmented selector; the
  // NAMD run-control row (with "＋ New job") is moved into #namd-run-controls at init.
  const simBody = page.locator('#simulate-body')
  if (!(await simBody.isVisible())) await page.click('#simulate-heading')
  await expect(simBody).toBeVisible()
  await page.click('.engine-selector-btn[data-engine="namd"]')
  await expect(page.locator('#md-jobs-new-btn')).toBeVisible()
}

test.beforeEach(async ({ request }) => {
  const r = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH },
    headers: { 'Content-Type': 'application/json', 'X-NADOC-Doc': DOC },
  })
  expect(r.ok(), 'POST /design/load failed').toBeTruthy()
})

test('the wizard renders every ladder stage as a column', async ({ page }) => {
  const errors = []
  page.on('pageerror', e => errors.push(String(e)))

  await openDynamics(page)
  await page.click('#md-jobs-new-btn')

  const modal = page.locator('.modal--wizard')
  await expect(modal).toBeVisible()

  // 22 stage columns + the sticky parameter column. Asserted as "many", not as a
  // literal: the ladder's chunk split is a backend constant and this spec must not
  // become another place that hard-codes it.
  const headers = modal.locator('.wizard-stages thead th')
  await expect.poll(async () => headers.count(), { timeout: 30_000 })
    .toBeGreaterThan(15)

  // The parameter column stays put while the stage columns scroll under it.
  await expect(modal.locator('.wizard-stages thead th.param')).toHaveText('Parameter')

  // Something in the table must be highlighted as different from the stage before it —
  // that is the whole point of the view.
  await expect(modal.locator('.wizard-cell--changed').first()).toBeVisible()

  // Conditions are stated, not left implicit.
  await expect(modal.locator('.wizard-cond').first()).toBeVisible()

  expect(errors, `console/page errors: ${errors.join('\n')}`).toEqual([])
})

test('switching protocol changes the plan and the provenance chips', async ({ page }) => {
  await openDynamics(page)
  await page.click('#md-jobs-new-btn')
  const modal = page.locator('.modal--wizard')
  await expect(modal).toBeVisible()
  await expect(modal.locator('.wizard-stages thead th').first()).toBeVisible()

  const totals = modal.locator('.wizard-totals')
  await expect(totals).toContainText('stages')

  await modal.locator('.wizard-preset', { hasText: 'Match the literature' }).click()
  // The literature tier refuses a water-shell carve and SAYS so up front — but as a
  // policy, not a verdict: this plan cannot know whether the design fits (that needs a
  // solvation profile), so it must never stop the run being created. The fit check
  // belongs to the launch pre-flight.
  const carve = modal.locator('.wizard-cond', { hasText: 'water-shell carve is not allowed' })
  await expect(carve).toHaveCount(1)
  await expect(modal.locator('.wizard-cond--blocking')).toHaveCount(0)
  await expect(modal.locator('button', { hasText: 'Create job' })).toBeEnabled()
  // Its settings come from the protocol, so the chips say so.
  await expect(modal.locator('.wizard-chip--preset').first()).toBeVisible()

  // "Not an option" means LOCKED, not merely defaulted: a carved run is a different
  // experiment, so an override would make this tier's own name untrue.
  const allow = modal.locator('.wizard-field', { hasText: 'Allow a carve' })
  await expect(allow.locator('input[type=checkbox]')).toBeDisabled()
  await expect(allow.locator('input[type=checkbox]')).not.toBeChecked()
  await expect(allow.locator('.wizard-chip')).toHaveText('forced by the server')

  await modal.locator('.wizard-preset', { hasText: 'Optimised for the design' }).click()
  await expect(carve).toHaveCount(0)
  // ...and it goes back to being an ordinary editable choice on a tier that permits it.
  await expect(allow.locator('input[type=checkbox]')).toBeEnabled()
})

test('every stage parameter is editable, and edits highlight as protocol deviations',
  async ({ page }) => {
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    page.on('dialog', async d => { await d.accept('2') })   // the set-for-every-stage prompt

    await openDynamics(page)
    await page.click('#md-jobs-new-btn')
    const modal = page.locator('.modal--wizard')
    await expect(modal.locator('.wizard-cell--changed').first()).toBeVisible({ timeout: 30_000 })

    const row = modal.locator('tr', { has: page.locator('th', { hasText: 'Langevin damping' }) })
    const cell = row.locator('td').nth(3)
    const protocolValue = (await cell.textContent()).trim()

    // Click-to-edit, in place: the value only makes sense beside its neighbours.
    await cell.click()
    const input = cell.locator('input')
    await expect(input).toBeVisible()
    await input.fill('2')
    await input.press('Enter')
    await expect(cell).toHaveText('2')

    // The edit highlights as a departure from the PROTOCOL — a different question from
    // `--changed`, which is "differs from the stage before".
    await expect(cell).toHaveClass(/wizard-cell--overridden/)
    await expect(modal.locator('.wizard-override-summary')).toContainText('edited by hand')

    // One directive across every stage at once; 22 columns cell-by-cell is not usable.
    await row.locator('.wizard-row-all').click()
    await expect.poll(async () => modal.locator('.wizard-cell--overridden').count(),
                      { timeout: 20_000 }).toBeGreaterThan(10)
    await expect(modal.locator('.wizard-override-summary')).toContainText('every stage')

    // Reset restores the protocol everywhere.
    await modal.locator('.wizard-override-summary button').click()
    await expect(cell).toHaveText(protocolValue)
    await expect(modal.locator('.wizard-cell--overridden')).toHaveCount(0)

    expect(errors, `page errors: ${errors.join('\n')}`).toEqual([])
  })

test('the sticky header survives scrolling the stage table', async ({ page }) => {
  // The body's first column is itself sticky, so a header that did not outrank it let
  // scrolled rows overwrite the column names.
  await openDynamics(page)
  await page.click('#md-jobs-new-btn')
  const modal = page.locator('.modal--wizard')
  await expect(modal.locator('.wizard-cell--changed').first()).toBeVisible({ timeout: 30_000 })
  await modal.locator('.wizard-stages').evaluate(el => { el.scrollTop = 260 })
  const heads = await modal.locator('.wizard-stages thead th').allTextContents()
  expect(heads[0]).toBe('Parameter')
  expect(heads[1]).toMatch(/min/)          // the minimisation column, not a scrolled value
})

test('production offers a relaxation picker or says to run one first', async ({ page }) => {
  await openDynamics(page)
  await page.click('#md-jobs-new-btn')
  const modal = page.locator('.modal--wizard')
  await expect(modal).toBeVisible()

  await modal.locator('.wizard-mode', { hasText: 'Production' }).click()

  // Either a picker labelled "<part> run created <time>" (never a hex job id), or the
  // explicit empty state. Both are correct; which one depends on the workspace.
  const empty = modal.locator('.wizard-empty')
  const picker = modal.locator('.wizard-field select')
  await expect(empty.or(picker).first()).toBeVisible({ timeout: 20_000 })
  if (await empty.count()) {
    await expect(empty).toContainText(/relaxation/i)
  } else {
    await expect(picker.first().locator('option').first()).toContainText(/run created/)
  }
})
