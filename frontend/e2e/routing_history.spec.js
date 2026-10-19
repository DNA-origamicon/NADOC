import { test, expect } from '@playwright/test'
import { withHistoryFixture } from './helpers/deformation_history.js'

test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')

const proof = async (request, headers) => {
  const response = await request.get('http://127.0.0.1:8004/api/__e2e__/history/proof', { headers })
  expect(response.ok()).toBe(true)
  expect((await response.json()).status).toBe('verified')
}
const staples = design => design.strands.filter(s => s.strand_type === 'staple' && !s.is_reference)

test('Fine Routing step editor edits a positional resize and the part stays verified', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    await page.locator('.left-tab-btn[data-tab="feature-log"]').click()
    await page.getByTitle('Expand Fine Routing', { exact: true }).last().click()
    await page.getByRole('button', { name: '✎' }).and(page.locator('[title$=" inputs"]')).last().click()
    const modal = page.getByRole('dialog', { name: 'Edit Resize strand ends', exact: true })
    await expect(modal).toBeVisible()
    // Positional (v2): the step names the strand end by helix/bp/direction, not an id.
    await expect(modal.getByLabel('Entry 1 Strand end at Base index', { exact: true })).toHaveValue('0')
    await expect(modal.getByLabel('Entry 1 Helix ID', { exact: true })).toHaveCount(0)
    await modal.getByLabel('Entry 1 Delta (bp)', { exact: true }).fill('-3')
    const edited = page.waitForResponse(r => /\/api\/design\/features\/\d+\/edit/.test(new URL(r.url()).pathname))
    await modal.getByRole('button', { name: 'Apply', exact: true }).click()
    expect((await edited).ok()).toBe(true)
    await expect(modal).not.toBeVisible()
    const { design } = await f.checkpoint()
    const child = design.feature_log.at(-1).children.at(-1)
    expect(child.params._proof_version).toBe(2)
    expect(child.params.entries[0].delta_bp).toBe(-3)
    await proof(request, f.headers)
  }, 'routing')
})

test('Autostaple offers selection-only vs entire structure and keeps unselected staples', async ({ page, request }) => {
  await withHistoryFixture({ page, request }, 'bend', async f => {
    const before = (await f.checkpoint()).design
    const target = staples(before).find(s => s.domains.length >= 2)
    await page.evaluate(id => window.__nadocTest.selectRefsForTest([{ kind: 'strand', id }]), target.id)
    // Optional visual evidence (explicit opt-in directory; nothing written otherwise).
    const capture = process.env.NADOC_ROUTING_E2E_CAPTURE
    const shot = async name => { if (capture) await page.screenshot({ path: `${capture}/${name}.png` }) }
    await page.waitForTimeout(capture ? 3000 : 0)
    await shot('region-autostaple-selected')
    // Shortcut [2] is the menu item's own key binding (same click handler).
    const openAutostaple = async () => {
      await page.evaluate(() => document.activeElement?.blur())
      await page.keyboard.press('2')
    }
    await openAutostaple()
    const chooser = page.getByRole('dialog', { name: 'Autostaple scope', exact: true })
    await expect(chooser).toBeVisible()
    await expect(chooser).toContainText('Selection only restaples every staple that touches the selection')
    await chooser.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(chooser).not.toBeVisible()
    expect((await f.checkpoint()).design.feature_log.length).toBe(before.feature_log.length)

    await openAutostaple()
    const done = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/full-autostaple')
    await chooser.getByRole('button', { name: 'Selection only', exact: true }).click()
    const response = await done
    expect(response.ok()).toBe(true)
    const body = response.request().postDataJSON()
    expect(body.region.length).toBeGreaterThan(0)
    await expect(page.locator('.toast-message', { hasText: 'Region autostaple complete' })).toBeVisible()
    await page.waitForTimeout(capture ? 2500 : 0)
    await shot('region-autostaple-after')
    const after = (await f.checkpoint()).design
    expect(after.feature_log.at(-1).label).toBe('Region autostaple')
    const kept = staples(before).filter(s => !s.domains.some(d => body.region.some(r =>
      r.helix_id === d.helix_id && Math.min(d.start_bp, d.end_bp) <= r.hi_bp && r.lo_bp <= Math.max(d.start_bp, d.end_bp))))
    expect(kept.length).toBeGreaterThan(0)
    for (const strand of kept) {
      const now = after.strands.find(s => s.id === strand.id)
      // Topology and assigned sequences are kept; a cleared sequence is re-derived.
      expect(now).toEqual(strand.sequence == null ? { ...strand, sequence: now.sequence } : strand)
      expect(now.sequence).toBeTruthy()
    }
    await proof(request, f.headers)
  }, 'routing')
})
