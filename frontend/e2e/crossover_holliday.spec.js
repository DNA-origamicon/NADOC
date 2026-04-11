/**
 * Playwright test: manual crossover placement (Holliday junction).
 *
 * Creates a 2-helix HC bundle, places two adjacent staple crossovers (bp 6+7)
 * to form a Holliday junction, and verifies via API + screenshots that:
 *   - Nucleotide coverage is identical before and after each crossover.
 *   - Strand count changes are correct (ligation creates multi-domain strands).
 *   - No strands are accidentally deleted.
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000/api'

// HC crossover bow-right set (staple)
const HC_STAP_BOW_RIGHT = new Set([0, 7, 14])
const HC_PERIOD = 21

function nickPositions(bp, dirA, dirB) {
  const bowDir = HC_STAP_BOW_RIGHT.has(bp % HC_PERIOD) ? +1 : -1
  const lowerBp = bowDir === +1 ? bp - 1 : bp
  const nickA = dirA === 'FORWARD' ? lowerBp : lowerBp + 1
  const nickB = dirB === 'FORWARD' ? lowerBp : lowerBp + 1
  return { nickA, nickB }
}

function coverage(design) {
  const cov = new Set()
  for (const s of design.strands) {
    for (const d of s.domains) {
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      for (let bp = lo; bp <= hi; bp++) {
        cov.add(`${d.helix_id}|${bp}|${d.direction}`)
      }
    }
  }
  return cov
}

function stapleSummary(design) {
  return design.strands
    .filter(s => s.strand_type === 'staple')
    .map(s => ({
      id: s.id,
      domains: s.domains.length,
      nt: s.domains.reduce((sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0),
      helices: [...new Set(s.domains.map(d => d.helix_id))],
    }))
}

test.describe('Holliday junction crossover placement', () => {

  test('coverage preserved through two adjacent crossovers', async ({ page }) => {
    // Create a 2-helix HC bundle via API
    const bundleRes = await page.request.post(`${API}/design/bundle`, {
      data: { cells: [[0, 0], [0, 1]], length_bp: 42, name: 'hj_test', plane: 'XY' },
    })
    expect(bundleRes.ok()).toBeTruthy()
    const bundle = await bundleRes.json()
    const design0 = bundle.design

    const ha = design0.helices.find(h => h.grid_pos[0] === 0 && h.grid_pos[1] === 0).id
    const hb = design0.helices.find(h => h.grid_pos[0] === 0 && h.grid_pos[1] === 1).id
    // Even parity: staple = REVERSE on ha, FORWARD on hb
    const da = 'REVERSE', db = 'FORWARD'

    const cov0 = coverage(design0)
    const staples0 = stapleSummary(design0)
    console.log('Before crossovers:', JSON.stringify(staples0, null, 2))

    // Place first crossover at bp=6 (bow-left)
    const nicks6 = nickPositions(6, da, db)
    const r1 = await page.request.post(`${API}/design/crossovers/place`, {
      data: {
        half_a: { helix_id: ha, index: 6, strand: da },
        half_b: { helix_id: hb, index: 6, strand: db },
        nick_bp_a: nicks6.nickA, nick_bp_b: nicks6.nickB,
      },
    })
    expect(r1.ok()).toBeTruthy()
    const design1 = (await r1.json()).design

    const cov1 = coverage(design1)
    const staples1 = stapleSummary(design1)
    console.log('After bp=6:', JSON.stringify(staples1, null, 2))

    // Verify coverage unchanged
    const lost1 = [...cov0].filter(x => !cov1.has(x))
    const gained1 = [...cov1].filter(x => !cov0.has(x))
    expect(lost1).toEqual([])
    expect(gained1).toEqual([])

    // Should have one multi-domain strand from ligation
    const multiDomain1 = staples1.filter(s => s.domains > 1)
    expect(multiDomain1.length).toBe(1)

    // Place second crossover at bp=7 (bow-right, completing Holliday junction)
    const nicks7 = nickPositions(7, da, db)
    const r2 = await page.request.post(`${API}/design/crossovers/place`, {
      data: {
        half_a: { helix_id: ha, index: 7, strand: da },
        half_b: { helix_id: hb, index: 7, strand: db },
        nick_bp_a: nicks7.nickA, nick_bp_b: nicks7.nickB,
      },
    })
    expect(r2.ok()).toBeTruthy()
    const design2 = (await r2.json()).design

    const cov2 = coverage(design2)
    const staples2 = stapleSummary(design2)
    console.log('After bp=7 (Holliday junction):', JSON.stringify(staples2, null, 2))

    // Verify coverage unchanged after second crossover
    const lost2 = [...cov0].filter(x => !cov2.has(x))
    const gained2 = [...cov2].filter(x => !cov0.has(x))
    expect(lost2).toEqual([])
    expect(gained2).toEqual([])

    // Two multi-domain strands, each spanning both helices
    const multiDomain2 = staples2.filter(s => s.domains > 1)
    expect(multiDomain2.length).toBe(2)
    for (const s of multiDomain2) {
      expect(s.helices.length).toBe(2)
    }

    // Total nucleotide count must match
    const totalNt0 = staples0.reduce((s, x) => s + x.nt, 0)
    const totalNt2 = staples2.reduce((s, x) => s + x.nt, 0)
    expect(totalNt2).toBe(totalNt0)
  })

  test('visual snapshot: cadnano editor after Holliday junction', async ({ page }) => {
    // Load the app
    await page.goto('/')
    await expect(page.locator('#canvas')).toBeVisible()

    // Create bundle via API and reload design in UI
    const bundleRes = await page.request.post(`${API}/design/bundle`, {
      data: { cells: [[0, 0], [0, 1]], length_bp: 42, name: 'hj_snap', plane: 'XY' },
    })
    expect(bundleRes.ok()).toBeTruthy()

    // Trigger UI refresh
    await page.evaluate(() => window.dispatchEvent(new Event('nadoc:design-changed')))
    await page.waitForTimeout(500)

    // Switch to cadnano editor (press K)
    await page.keyboard.press('k')
    await page.waitForTimeout(1000)

    // Screenshot before crossovers
    await page.screenshot({ path: 'e2e/screenshots/hj_before.png', fullPage: true })

    // Get helix IDs
    const design0 = (await (await page.request.get(`${API}/design`)).json())
    const ha = design0.helices.find(h => h.grid_pos[0] === 0 && h.grid_pos[1] === 0).id
    const hb = design0.helices.find(h => h.grid_pos[0] === 0 && h.grid_pos[1] === 1).id
    const da = 'REVERSE', db = 'FORWARD'

    // Place Holliday junction (bp 6+7)
    for (const bp of [6, 7]) {
      const nicks = nickPositions(bp, da, db)
      const r = await page.request.post(`${API}/design/crossovers/place`, {
        data: {
          half_a: { helix_id: ha, index: bp, strand: da },
          half_b: { helix_id: hb, index: bp, strand: db },
          nick_bp_a: nicks.nickA, nick_bp_b: nicks.nickB,
        },
      })
      expect(r.ok()).toBeTruthy()
    }

    // Trigger UI refresh and wait for render
    await page.evaluate(() => window.dispatchEvent(new Event('nadoc:design-changed')))
    await page.waitForTimeout(1000)

    // Screenshot after crossovers
    await page.screenshot({ path: 'e2e/screenshots/hj_after.png', fullPage: true })

    // Verify via API that coverage is correct
    const designFinal = (await (await page.request.get(`${API}/design`)).json())
    const staples = designFinal.strands.filter(s => s.strand_type === 'staple')
    const totalNt = staples.reduce((sum, s) =>
      sum + s.domains.reduce((ds, d) => ds + Math.abs(d.end_bp - d.start_bp) + 1, 0), 0)

    // 2 helices * 42 bp * 2 directions (staple side only) = 84 nt
    expect(totalNt).toBe(84)
    expect(designFinal.crossovers.length).toBe(2)
  })
})
