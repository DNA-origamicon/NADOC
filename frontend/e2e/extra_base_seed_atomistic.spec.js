/**
 * With "Adjust for Extra Bases" ON, the ATOMISTIC reps must show the t=0
 * pre-minimisation coordinates for EVERY atom — not just the inserts.
 *
 * The ordinary display build uses cheap interpolated phosphodiester linkers and
 * the as-designed lattice; the seed build uses the exact linker minimiser at the
 * expanded lattice. They differ by ~3 A per atom on an insert-carrying design,
 * and the linker atoms are precisely what a junction clash is made of.
 *
 * The oracle is the backend's own two builds: fetch both and require the drawn
 * atoms to match the SEED one and not the display one.
 */

import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const WORKSPACE = '/home/jojo/Work/NADOC/workspace'
const STEM = 'e2exbatom'
const DOC = 'xbatom'

async function drawnAtomCentres(page) {
  return page.evaluate(() => {
    const out = []
    window.__nadocTest.scene.traverse(o => {
      if (!o.isInstancedMesh || !/atom/i.test(o.name || '')) return
      const a = o.instanceMatrix.array
      for (let i = 0; i < o.count; i++) out.push([a[i * 16 + 12], a[i * 16 + 13], a[i * 16 + 14]])
    })
    return out
  })
}

test.describe('MD seed atomistic view', () => {
  test.setTimeout(300_000)

  test.beforeAll(() => {
    fs.copyFileSync(path.join(WORKSPACE, '6hbx100_2xT.nadoc'), path.join(WORKSPACE, `${STEM}.nadoc`))
  })
  test.afterAll(() => {
    fs.rmSync(path.join(WORKSPACE, `${STEM}.nadoc`), { force: true })
  })

  test('toggle switches the atomistic rep to seed coordinates', async ({ page }) => {
    await page.goto(`/?doc=${DOC}`)
    await page.waitForSelector('#canvas')
    const welcome = page.locator('#welcome-screen')
    await welcome.locator('.lib-row-name', { hasText: new RegExp(`^${STEM}$`) })
      .first().click({ timeout: 60_000 })
    await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
    await page.waitForFunction(() => {
      let n = 0
      window.__nadocTest?.scene?.traverse(o => {
        if (o.isInstancedMesh && o.name === 'backboneSpheres') n += o.count
      })
      return n > 0
    }, null, { timeout: 60_000 })

    // Both backend builds, as the oracle. Kept INSIDE the page and compared there:
    // the sets are ~30k keys each, and shipping them across the boundary once per
    // poll is what made an earlier version of this test compare a truncated oracle
    // against the full drawn set (max attainable fraction 0.13, threshold 0.5).
    const builds = await page.evaluate(async (doc) => {
      const h = { 'X-NADOC-Doc': doc }
      const disp = await (await fetch('/api/design/atomistic', { headers: h })).json()
      const seed = await (await fetch('/api/design/atomistic?seed_lattice_nm=auto', { headers: h })).json()
      const key = m => m.atoms.map(a => `${a.x.toFixed(2)},${a.y.toFixed(2)},${a.z.toFixed(2)}`)
      const dispKeys = key(disp), seedKeys = key(seed)
      window.__seedProbe = { disp: new Set(dispKeys), seed: new Set(seedKeys) }
      return {
        nDisp: disp.atoms.length, nSeed: seed.atoms.length,
        seedLattice: seed.lattice_nm, isSeed: seed.seed,
        identical: dispKeys.filter((k, i) => k === seedKeys[i]).length / dispKeys.length,
      }
    }, DOC)
    expect(builds.isSeed).toBe(true)
    expect(builds.seedLattice).toBeCloseTo(2.55, 2)
    expect(builds.nSeed).toBe(builds.nDisp)
    // The two builds must genuinely differ, or this test proves nothing.
    expect(builds.identical, 'display and seed builds should differ').toBeLessThan(0.2)

    // Enter ball & stick.
    await page.locator('.menu-item').filter({ hasText: 'View' }).first().hover()
    await page.locator('.submenu-item').filter({ hasText: 'Representation' }).first().hover()
    await page.click('#menu-view-atomistic-ballstick')
    await expect.poll(async () => (await drawnAtomCentres(page)).length,
      { timeout: 180_000, message: 'atomistic rep never drew atoms' }).toBeGreaterThan(0)

    /** Fraction of DRAWN atom centres sitting on one of the two builds' coordinates. */
    const frac = (which) => page.evaluate((w) => {
      const set = window.__seedProbe[w]
      let hit = 0, n = 0
      window.__nadocTest.scene.traverse(o => {
        if (!o.isInstancedMesh || !/atom/i.test(o.name || '')) return
        const a = o.instanceMatrix.array
        for (let i = 0; i < o.count; i++) {
          const k = [a[i * 16 + 12], a[i * 16 + 13], a[i * 16 + 14]]
            .map(v => v.toFixed(2)).join(',')
          if (set.has(k)) hit++
          n++
        }
      })
      return n ? hit / n : 0
    }, which)

    // Before the toggle: drawn atoms are the DISPLAY build.
    const d0 = await frac('disp'), s0 = await frac('seed')
    expect(d0, `display ${d0.toFixed(3)} vs seed ${s0.toFixed(3)}`).toBeGreaterThan(s0 + 0.2)

    // Toggle on → drawn atoms become the SEED build.
    //
    // Asserted as a MARGIN over the display build, not an absolute fraction: the
    // match is computed by rounding to 0.01 nm, so atoms whose two builds agree to
    // within a rounding boundary land in different buckets and neither set ever
    // reaches 1.0. Which build the atoms came from is the question; how kindly the
    // coordinates round is not.
    await page.locator('.menu-item').filter({ hasText: 'View' }).first().hover()
    await page.click('#menu-view-extra-base-spacing')
    await expect.poll(async () => (await frac('seed')) - (await frac('disp')), {
      timeout: 240_000,
      message: 'atomistic rep never switched to seed coordinates',
    }).toBeGreaterThan(0.2)

    // Toggle off → back to the display build.
    await page.locator('.menu-item').filter({ hasText: 'View' }).first().hover()
    await page.click('#menu-view-extra-base-spacing')
    await expect.poll(async () => (await frac('disp')) - (await frac('seed')), {
      timeout: 120_000,
      message: 'atomistic rep never returned to the display build',
    }).toBeGreaterThan(0.2)
  })
})
