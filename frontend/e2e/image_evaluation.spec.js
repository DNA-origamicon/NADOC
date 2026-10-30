/** Read-only PDF workflow. No workspace writes, downloads, or persistent captures.
 * Isolated smoke server disables session cache; global teardown handles bridge key.
 */
import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

function routingPDF() {
  const commands = ['0.5 G', '0.6 w']
  for (let r = 0; r < 6; r++) { const y = 40 + r * 20; commands.push(`25 ${y} m 95 ${y} l S 97 ${y} m 200 ${y} l S`) }
  for (const x of [60, 80, 100, 145]) for (const r of [0, 2, 4]) {
    const y = 40 + r * 20
    commands.push(`${x-10} ${y} m ${x} ${y} l ${x-1} ${y+6} ${x-1} ${y+14} ${x} ${y+20} c ${x-10} ${y+20} l S`)
  }
  const stream = commands.join('\n')
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 230] /Contents 4 0 R >>', `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`]
  let data = '%PDF-1.4\n'; const offsets = [0]
  objects.forEach((obj, i) => { offsets.push(Buffer.byteLength(data)); data += `${i+1} 0 obj\n${obj}\nendobj\n` })
  const start = Buffer.byteLength(data)
  data += `xref\n0 5\n0000000000 65535 f \n${offsets.slice(1).map(n => `${String(n).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`
  return Buffer.from(data)
}

test('Help PDF evaluation detects routing, annotates flags, and calibrates indices', async ({ page }) => {
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.locator('#menu-help-experimental').hover(); await page.locator('#menu-help-image-evaluation').click()
  await expect(page.locator('.ie-modal')).toBeVisible()
  await page.locator('.ie-modal [data-file]').setInputFiles({ name: 'routing.pdf', mimeType: 'application/pdf', buffer: routingPDF() })
  await expect(page.locator('.ie-modal [data-status]')).toContainText('1 routing candidate')
  await page.locator('.ie-modal [data-candidates] button').click()
  await expect(page.locator('.ie-modal [data-summary]')).toContainText('6 inferred rows')
  await page.locator('.ie-modal [data-flags] button').filter({ hasText: 'spacing:' }).first().click()
  await expect(page.locator('.ie-modal [data-detail]')).toContainText('stretched')
  await page.locator('.ie-modal [data-first]').fill('13'); await page.locator('.ie-modal [data-first]').press('Tab')
  await expect(page.locator('.ie-modal [data-stage] svg')).toContainText('~13')
  await page.locator('.ie-modal [data-layer="ends"]').check()
  await expect(page.locator('.ie-modal [data-stage] svg circle[fill="#ce3248"]').first()).toBeVisible()
  await page.route('**/api/image-evaluation/brick-matches?*', route => route.fulfill({ json: {
    reference: { title: 'Gerling 2018 · Table S1 · Brick' }, design_name: 'Sequence overlay fixture', minimum: 12,
    domains_checked: 2, skipped_strands: [], helices: Array.from({ length: 6 }, (_, i) => ({ id: `h${i}`, label: `Helix ${i}` })),
    matches: [
      { strand_id: 's1', strand_name: 'Staple 1', domain_index: 0, helix_id: 'h2', offset: 0, length: 14, sequence: 'CAGACAGCCCTCATG', start_bp: 14, end_bp: 27, full_domain: true, published_index: 5, published_offset: 4 },
      { strand_id: 's2', strand_name: 'Staple 2', domain_index: 1, helix_id: 'h4', offset: 1, length: 12, sequence: 'CAATACTGCGGAA', start_bp: 29, end_bp: 18, full_domain: false, published_index: 41, published_offset: 5 },
    ],
  } }))
  await page.locator('[data-brick-toggle]').check()
  await expect(page.locator('[data-brick-match]')).toHaveCount(2)
  await expect(page.locator('[data-brick-status]')).toContainText('2/2 matching spans visible')
  await page.locator('[data-brick-match]').first().click()
  await expect(page.locator('[data-detail]')).toContainText('Brick 5 (base 5)')
  if (process.env.NADOC_BRICK_OVERLAY_CAPTURE) await page.screenshot({ path: process.env.NADOC_BRICK_OVERLAY_CAPTURE, fullPage: true })
  await page.locator('[data-brick-toggle]').uncheck()
  await expect(page.locator('[data-brick-match]')).toHaveCount(0)
  await page.locator('.ie-modal .modal__close').click()
  await expect(page.locator('.ie-modal')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('Gerling supplement exposes the stretched S1 intervals', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  test.skip(!process.env.NADOC_IMAGE_EVALUATION_PDF, 'Optional external scientific source; no PDF copied into repository.')
  await page.goto('/'); await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover(); await page.locator('#menu-help-experimental').hover(); await page.locator('#menu-help-image-evaluation').click()
  await page.locator('.ie-modal [data-file]').setInputFiles(process.env.NADOC_IMAGE_EVALUATION_PDF)
  const s1 = page.locator('.ie-modal [data-candidates] button').filter({ hasText: 'Page 3 ·' })
  await expect(s1).toBeVisible({ timeout: 45000 }); await s1.click()
  await expect(page.locator('.ie-modal [data-summary]')).toContainText('42 inferred rows')
  await expect(page.locator('.ie-modal [data-summary]')).toContainText('453 branches')
  await page.locator('.ie-modal [data-first]').fill('6'); await page.locator('.ie-modal [data-first]').press('Tab')
  await expect(page.locator('.ie-modal [data-stage] svg')).toContainText('~13')
  await expect(page.locator('.ie-modal [data-flags] button').filter({ hasText: 'spacing:' })).toHaveCount(4)
  await expect(page.locator('.ie-modal [data-flags] button').filter({ hasText: 'Rows 1–2: no junction detected at column 0' })).toHaveCount(1)
  await page.locator('.ie-modal [data-flags] button').filter({ hasText: 'spacing:' }).first().click()
  if (process.env.NADOC_BRICK_MATCHES_PATH) {
    const matches = JSON.parse(await readFile(process.env.NADOC_BRICK_MATCHES_PATH, 'utf8'))
    await page.route('**/api/image-evaluation/brick-matches?*', route => route.fulfill({ json: matches }))
    await page.locator('[data-brick-toggle]').check()
    await expect(page.locator('[data-brick-match]').first()).toBeVisible()
    await expect(page.locator('[data-brick-status]')).toContainText('36/666 domains')
    if (process.env.NADOC_BRICK_OVERLAY_CAPTURE) await page.screenshot({ path: process.env.NADOC_BRICK_OVERLAY_CAPTURE.replace('.png', '-gerling.png'), fullPage: true })
  }
  if (process.env.NADOC_IMAGE_EVALUATION_CAPTURE === '1') {
    const capture = testInfo.outputPath('review.png')
    await page.screenshot({ path: capture })
    console.log(`IMAGE_EVALUATION_REVIEW=${capture}`)
    await page.waitForTimeout(20000) // Inspection window; cleanup reporter always removes this capture.
  }
  await page.locator('.ie-modal .modal__close').click()
})


test('Gerling Page 3 matches use the active document through the real API', async ({ page, request }) => {
  test.setTimeout(120000)
  test.skip(!process.env.NADOC_IMAGE_EVALUATION_PDF || !process.env.NADOC_GERLING_DESIGN, 'Requires external Gerling PDF and saved design.')
  const api = process.env.NADOC_E2E_API_BASE
  const created = await request.post(`${api}/api/documents`, { data: {} })
  expect(created.ok()).toBeTruthy()
  const { doc_id: doc } = await created.json()
  const headers = { 'X-NADOC-Doc': doc }
  try {
    const loaded = await request.post(`${api}/api/design/load`, { headers, data: { path: process.env.NADOC_GERLING_DESIGN }, timeout: 60000 })
    expect(loaded.ok()).toBeTruthy()
    // Reproduce the old unscoped request: default document has no active design.
    const unscoped = await request.get(`${api}/api/image-evaluation/brick-matches`)
    expect(unscoped.status()).toBe(404)
    await page.goto(`/?doc=${encodeURIComponent(doc)}`)
    await page.waitForFunction(() => !!window.__nadocTest)
    await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
    await page.locator('#menu-help-experimental').hover(); await page.locator('#menu-help-image-evaluation').click()
    await page.locator('[data-file]').setInputFiles(process.env.NADOC_IMAGE_EVALUATION_PDF)
    const s1 = page.locator('[data-candidates] button').filter({ hasText: 'Page 3 ·' })
    await expect(s1).toBeVisible({ timeout: 45000 }); await s1.click()
    const responsePromise = page.waitForResponse(r => r.url().includes('/image-evaluation/brick-matches'))
    await page.locator('[data-sequence-reference]').selectOption('brick')
    const response = await responsePromise
    expect(response.request().headers()['x-nadoc-doc']).toBe(doc)
    expect(response.ok()).toBeTruthy()
    const matches = await response.json()
    expect(matches.design_name).toContain('Gerling2018')
    await expect(page.locator('[data-brick-status]')).toContainText('36/666 domains')
    await expect(page.locator('[data-brick-match]').first()).toBeVisible()
    // Retain the ordinary first-BP=0 condition before adjusting the known S1 calibration.
    expect(await page.locator('[data-brick-match]').count()).toBeGreaterThan(0)
    await page.locator('[data-first]').fill('6'); await page.locator('[data-first]').press('Tab')
    await expect(page.locator('[data-brick-match]')).toHaveCount(31)
    await page.locator('[data-brick-match]').first().click()
    await expect(page.locator('[data-detail]')).toContainText('Brick 41')
    await page.locator('[data-sequence-reference]').selectOption('42hb13')
    await expect(page.locator('[data-brick-status]')).toContainText('42hb (1)-(3)')
    await page.locator('[data-sequence-register]').selectOption('17')
    await expect(page.locator('[data-brick-status]')).toContainText('p7560 offset 17: hypothetical')
    await page.locator('[data-reconstruction-toggle]').check()
    await expect(page.locator('[data-reconstruction-position]')).toHaveCount(4)
    await page.locator('[data-reconstruction-position="41:37.5"]').click()
    await expect(page.locator('[data-detail]')).toContainText('Helix 41: proposed nick 37/38')
    await expect(page.locator('[data-detail]')).not.toContainText('h_XY_')
    // Bring the lower-helix evidence back into view after the SVG redraw.
    await page.locator('[data-reconstruction-position="41:37.5"]').scrollIntoViewIfNeeded()
    await expect(page.locator('[data-reconstruction-position="41:37.5"]')).toBeInViewport()
    if (process.env.NADOC_BRICK_OVERLAY_CAPTURE) await page.screenshot({ path: process.env.NADOC_BRICK_OVERLAY_CAPTURE.replace('.png', '-real-api.png'), fullPage: false })
    await page.locator('[data-reconstruction-toggle]').uncheck()
    await expect(page.locator('[data-reconstruction-position]')).toHaveCount(0)
    await page.locator('[data-brick-toggle]').uncheck()
    await expect(page.locator('[data-brick-match]')).toHaveCount(0)
    await page.locator('.ie-modal .modal__close').click()
  } finally {
    await request.delete(`${api}/api/documents/${encodeURIComponent(doc)}`)
  }
})
