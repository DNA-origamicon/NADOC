import { test, expect } from '@playwright/test'
import { PegCoatingDriver } from './helpers/peg_coating_driver.js'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Scratch fixture is removed by afterAll and global teardown, including on failure.
// No engine calls, downloads or job artifacts; session cache is disabled.
const root = fileURLToPath(new URL('../../', import.meta.url))
const design = execFileSync(`${root}/.venv/bin/python`, ['-c', 'from scripts.create_peg_surface_review import make_review_design; d=make_review_design(); d.metadata.name="__e2e__peg-coating"; print(d.model_dump_json())'], { cwd: root, encoding: 'utf8' })

const fixture = `${root}/workspace/playwright_tests/__e2e__peg-coating.nadoc`
test.beforeAll(() => {
  mkdirSync(`${root}/workspace/playwright_tests`, { recursive: true })
  writeFileSync(fixture, design, { flag: 'wx' })
})
test.afterAll(() => rmSync(fixture, { force: true }))

async function openCoating(page, job = null) {
  await page.route(/\/(oxdna|md|mrdna|lammps)\/jobs(?:\?.*)?$/, route =>
    route.request().method() === 'GET' ? route.fulfill({ json: job && route.request().url().includes('/oxdna/') ? [job] : [] }) : route.abort())
  await page.goto('/?doc=__e2e__peg-coating&open=playwright_tests/__e2e__peg-coating.nadoc&open-type=design')
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await page.locator('#oxdna-floor-toggle').click()
  await page.locator('#oxdna-floor-enable').check()
  await page.locator('#oxdna-peg-enable').check()
}

test('PEG numbers match adjacent sidebar inputs and remain readable', async ({ page }) => {
  await openCoating(page)
  const styles = await page.locator('#oxdna-peg-controls input[type=number], #oxdna-floor-stiff').evaluateAll(nodes => nodes.map(node => {
    const s = getComputedStyle(node)
    return { id: node.id, color: s.color, background: s.backgroundColor }
  }))
  const reference = styles.find(s => s.id === 'oxdna-floor-stiff')
  for (const field of styles) {
    expect(field.color, field.id).toBe(reference.color)
    expect(field.background, field.id).toBe(reference.background)
    const luminance = rgb => {
      const c = rgb.match(/\d+/g).slice(0, 3).map(v => {
        const s = Number(v) / 255
        return s <= .04045 ? s / 12.92 : ((s + .055) / 1.055) ** 2.4
      })
      return c[0] * .2126 + c[1] * .7152 + c[2] * .0722
    }
    expect((luminance(field.color) + .05) / (luminance(field.background) + .05)).toBeGreaterThanOrEqual(4.5)
  }
  await expect(page.locator('#oxdna-peg-segments')).toBeVisible()
})


test('user configures, reviews and sends PEG through the job wizard without an engine', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await openCoating(page)
  await page.locator('#oxdna-floor-offset').fill('-10')
  const driver = new PegCoatingDriver(page)
  await driver.configure({ segments: 12, bondLengthNm: .8, beadDiameterNm: .6,
    terminalChargeE: -.5, shape: 'square', sizeNm: 20, densityPerUm2: 10000,
    offsetXNm: 2.5, offsetYNm: -1.5, seed: 42 })
  const review = await driver.review()
  expect(review.summary).toEqual({ requested_chains: 4, beads_per_chain: 13, requested_beads: 52 })
  await expect(page.locator('#oxdna-peg-review-result')).toContainText('No job created.')
  await expect(page.locator('#oxdna-peg-review-result')).toContainText('physical electric field')
  // Invalid raw values must not be silently clamped into a valid reviewed setup.
  await page.locator('#oxdna-peg-segments').fill('65')
  await expect(page.locator('#oxdna-peg-review-result')).toBeEmpty()
  await page.locator('#oxdna-peg-review').click()
  await expect(page.locator('#oxdna-peg-review-result')).toContainText('Enter valid values')
  await page.locator('#oxdna-peg-segments').fill('12')

  let submitted = null, starts = 0
  await page.route('**/api/oxdna/jobs/estimate-disk', route => route.fulfill({ json: { warn: false, free_bytes: 1e12, predicted_bytes: 1024, free_after_bytes: 1e12 - 1024 } }))
  await page.route('**/api/oxdna/jobs', async route => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: [] })
    submitted = route.request().postDataJSON()
    await route.fulfill({ status: 400, json: { detail: 'Test stopped at engine preparation boundary' } })
  })
  await page.route('**/api/oxdna/jobs/*/start', route => { starts++; return route.abort() })
  await page.locator('#oxdna-jobs-new-btn').click()
  const wizard = page.locator('.modal--oxdna-wizard')
  await expect(wizard).toBeVisible()
  await wizard.locator('.wizard-tab', { hasText: 'Full configuration' }).click()
  await wizard.locator('.modal__actions button', { hasText: 'Create job' }).click()
  await expect.poll(() => submitted).not.toBeNull()
  expect(submitted.surface_strands).toMatchObject(review.job_request_fragment.surface_strands)
  expect(submitted.surface).toMatchObject(review.job_request_fragment.surface)
  expect(submitted.autostart).toBe(false)
  expect(starts).toBe(0)
  expect(errors).toEqual([])
})


test('PEG Live starts, renders CM frames and stops using its independent capability', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const saved = JSON.parse(design).metadata.peg_surface
  const job = { job_id: '__e2e__peg-live', design_name: '__e2e__peg-coating',
    design_source_path: 'playwright_tests/__e2e__peg-coating.nadoc',
    status: 'queued', backend: 'CPU', device: '0', stages: [], n_nucleotides: 68,
    created_at: '2026-09-11T00:00:00Z',
    run_config: { ...saved, kind: 'relax', backend: 'CPU', interaction_type: 'DNA2',
      surface_strands: { ...saved.surface_strands, built: { n_beads: 36,
        trap_particles: [32, 41, 50, 59], terminal_particles: [40, 49, 58, 67] } } } }
  let start = null, stops = 0
  await page.route('**/api/oxdna/live/available', route => route.fulfill({
    json: { available: false, reason: 'stock oxpy unavailable', peg: { available: true, reason: 'ready' } },
  }))
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [{ ...job, engine: 'oxdna', kind: 'relax' }] }))
  await page.route('**/api/oxdna/jobs/__e2e__peg-live**', route => route.fulfill({ json: job }))
  await page.route('**/api/oxdna/live/start', route => {
    start = route.request().postDataJSON()
    return route.fulfill({ json: { session_id: '__e2e__peg-session', status: 'running', backend: 'CPU' } })
  })
  await page.route('**/api/oxdna/live/__e2e__peg-session/frame', route => route.fulfill({ json: {
    ready: true, status: 'running', backend: 'CPU', n_bursts: 3, n_positions: 36,
    positions: Array.from({ length: 36 }, (_, i) => ({
      helix_id: `cap${Math.floor(i / 9)}`, bp_index: 1000000 + Math.floor(i / 9) * 1000 + i % 9,
      direction: 'FORWARD', cm_position: [2 + Math.floor(i / 9), -7 + i % 9 * .7, 3],
      backbone_position: [2 + Math.floor(i / 9), -7 + i % 9 * .7, 3], nx: 1, ny: 0, nz: 0,
    })),
  } }))
  await page.route('**/api/oxdna/live/__e2e__peg-session/stop', route => {
    stops++
    return route.fulfill({ json: { ok: true, stopped: true } })
  })
  await openCoating(page, job)
  const live = page.locator('#oxdna-jobs-live-btn')
  if (await live.isDisabled()) {
    await page.locator('#simulate-jobs-list [data-job-id="__e2e__peg-live"]').click()
  }
  await expect(live).toBeEnabled()
  await live.click()
  await expect(live).toContainText('Stop Live')
  await expect(page.locator('#oxdna-peg-segments')).toBeDisabled()
  await expect(page.locator('#oxdna-jobs-live-status')).toContainText('3 bursts')
  await expect.poll(() => page.evaluate(() => window.__nadocSurfStrands.debug().visible)).toBe(true)
  expect(start.job_id).toBe('__e2e__peg-live')
  expect(start.surface_strands).toMatchObject({ material: 'PEG', enabled: true, subjectToField: false })
  await expect.poll(() => page.evaluate(() => {
    let xyz = null
    window.__nadocTest.scene.traverse(object => {
      if (object.name === 'peg-surface-beads') xyz = Array.from(object.children[0].instanceMatrix.array.slice(12, 15))
    })
    return xyz
  })).toEqual([2, -7, 3])
  await live.click()
  await expect(live).toContainText('◉ Live')
  await expect(page.locator('#oxdna-peg-segments')).toBeEnabled()
  await expect.poll(() => stops).toBe(1)
  expect(errors).toEqual([])
})
