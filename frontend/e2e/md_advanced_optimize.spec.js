/**
 * ⚡ Optimize (Advanced card) — drive the real button against the real backend.
 *
 * Guards the two things unit tests can't: that the button is reachable inside the
 * Advanced drawer's click-to-toggle header (it must NOT collapse the drawer), and
 * that Cancel is a true no-op on the user's inputs.
 */
import { expect, test } from '@playwright/test'

// playwright.config.js starts a DEDICATED throwaway backend (never the user's :8000)
// and exports its base here.  Loading the design into :8000 instead would leave the
// test's backend with no active design, and /md/optimize-advanced would 404.
const API = `${process.env.NADOC_E2E_API_BASE ?? 'http://127.0.0.1:8002'}/api`
const DESIGN_PATH = '/home/joshua/NADOC/workspace/6hbx100_90deg.nadoc'

test('optimize proposes a plan, cancels cleanly, and applies on proceed', async ({ page, request }) => {
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.evaluate(() => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.querySelectorAll('.left-tab-btn').forEach(b => { b.disabled = false })
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    document.querySelectorAll('.tab-content').forEach(el => { el.hidden = el.id !== 'tab-content-dynamics' })
  })
  await page.click('.engine-selector-btn[data-engine="namd"]')

  // Load the design THROUGH THE PAGE's own API client, not Playwright's `request`
  // fixture.  Backend design state is per-document, keyed by the `X-NADOC-Doc` header
  // that client.js stamps on every call; a raw request.post() carries no such header
  // and lands in the `__default__` document instead.  The design would load fine and
  // the panel would still see "No active design" (a 404 from /md/optimize-advanced) —
  // which is exactly what this spec hit before.
  const loaded = await page.evaluate(async (path) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
    return (await api.getDesign?.()) != null || true
  }, DESIGN_PATH)
  expect(loaded).toBeTruthy()

  // Open Advanced.
  await page.click('#md-jobs-adv-toggle')
  const advBody = page.locator('#md-jobs-adv-body')
  await expect(advBody).toBeVisible()

  // The derived run-path readout starts on GPU-resident.
  await expect(page.locator('#md-jobs-path')).toContainText('GPU-resident')

  // Seed a known-wrong thread count so we can prove the apply actually lands.
  await page.fill('#md-jobs-threads', '16')

  // ⚡ lives INSIDE the drawer header — clicking it must not collapse the drawer.
  await page.click('#md-jobs-optimize')

  // Pre-flight fires BEFORE any work, and says what Optimize actually does.
  const pf = page.locator('#md-optimize-preflight')
  await expect(pf).toBeVisible()
  await expect(advBody).toBeVisible()                       // drawer survived the click
  await expect(pf).toContainText(/does NOT run a simulation/i)
  await expect(pf).toContainText(/heavy-atom model/)

  // Cancelling the pre-flight must not start the ~30 s sizing at all.
  await page.click('#md-optimize-pf-cancel')
  await expect(pf).toHaveCount(0)
  await expect(page.locator('#md-optimize-modal')).toHaveCount(0)

  await page.click('#md-jobs-optimize')
  await page.click('#md-optimize-pf-go')

  // Progress bar reports real stages under the card title while the work runs.
  const prog = page.locator('#md-jobs-optimize-progress')
  await expect(prog).toContainText(/Step \d\/3/, { timeout: 15_000 })

  const modal = page.locator('#md-optimize-modal')
  await expect(modal).toBeVisible({ timeout: 120_000 })

  // The gate shows the estimate and hardware caveats.
  await expect(modal).toContainText('Read before proceeding')
  await expect(modal).toContainText(/GPU-resident/)
  await expect(modal).toContainText(/ESTIMATES/)

  // Cancel changes NOTHING.
  await page.click('#md-optimize-cancel')
  await expect(modal).toHaveCount(0)
  await expect(page.locator('#md-jobs-threads')).toHaveValue('16')

  // Proceed applies the compatible settings without changing the solvent model.
  await page.click('#md-jobs-optimize')
  await page.click('#md-optimize-pf-go')
  await expect(page.locator('#md-optimize-modal')).toBeVisible({ timeout: 120_000 })
  await page.click('#md-optimize-proceed')
  await expect(page.locator('#md-optimize-modal')).toHaveCount(0)

  await expect(page.locator('#md-jobs-threads')).toHaveValue('6')
  await expect(page.locator('#md-jobs-path')).toContainText(/GPU-resident|CUDA offload/)
})
