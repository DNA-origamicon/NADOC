import { expect, test } from '@playwright/test'

async function openScientificReview(page) {
  await page.goto('/')
  const help = page.locator('#menu-bar > .menu-item').filter({
    has: page.locator('#menu-help-tt-cpd-scientific-review'),
  })
  await help.hover()
  await page.locator('#menu-help-tt-cpd-scientific-review').click()
  const modal = page.locator('.modal__overlay').filter({
    has: page.locator('.modal__title', { hasText: 'TT-CPD scientific review' }),
  })
  await expect(modal).toBeVisible()
  await expect(modal.getByText('Visual identity review only.')).toBeVisible()
  return modal
}

test('TT-CPD reviewer renders annotated 3D definitions, conformers, and decisions', async ({ page }) => {
  const errors = []
  let savedDecision = null
  page.on('console', message => {
    if (message.type() === 'error' && /WebGL|TT-CPD|scientific-review/i.test(message.text())) {
      errors.push(message.text())
    }
  })
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => {
    if (response.url().includes('/photoproducts/scientific-review') && !response.ok()) {
      errors.push(`${response.status()} ${response.url()}`)
    }
  })
  // Keep this UI-only check isolated from reconciliation of the user's persisted jobs.
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.route('**/api/design/photoproducts/scientific-review/decision', async route => {
    savedDecision = route.request().postDataJSON()
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        simulation_ready: false,
        gate_effect: 'none',
        decision: { ...savedDecision, reviewed_at: '2026-09-04T00:00:00+00:00' },
      }),
    })
  })

  const modal = await openScientificReview(page)
  const canvas = modal.locator('canvas')
  await expect(canvas).toBeVisible()
  const box = await canvas.boundingBox()
  expect(box.width).toBeGreaterThan(600)
  expect(box.height).toBeGreaterThan(400)
  expect(await canvas.evaluate(node => ({ width: node.width, height: node.height }))).toMatchObject({
    width: expect.any(Number), height: 500,
  })

  const decisionButtons = [
    modal.getByRole('button', { name: 'Approve' }),
    modal.getByRole('button', { name: 'Reject' }),
    modal.getByRole('button', { name: 'Revise' }),
  ]
  for (const button of decisionButtons) await expect(button).toBeVisible()
  const modalBox = await modal.locator('.modal').boundingBox()
  for (const button of decisionButtons) {
    const buttonBox = await button.boundingBox()
    expect(buttonBox.x).toBeGreaterThanOrEqual(modalBox.x)
    expect(buttonBox.x + buttonBox.width).toBeLessThanOrEqual(modalBox.x + modalBox.width)
  }
  await expect(modal.getByPlaceholder('Reviewer name')).toBeVisible()
  await expect(modal.getByPlaceholder(/Required: what you checked/)).toBeVisible()

  await expect(modal.getByText(/1:C5 — 2:C5|1:C5 — 2:C6/).first()).toBeVisible()
  await expect(modal.getByText(/1:C6 — 2:C6|1:C6 — 2:C5/).first()).toBeVisible()
  await expect(modal.getByText(/^1:C5 [RS] ·/)).toBeVisible()
  await expect(modal.getByText(/^2:C6 [RS] ·/)).toBeVisible()
  await expect(modal.getByText('Mirror operation used: NO')).toBeVisible()

  // OrbitControls must respond to an actual pointer drag, moving a projected 3D label.
  const label = modal.getByText(/^1:C5 [RS] ·/)
  const before = await label.boundingBox()
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.45)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.70, box.y + box.height * 0.35, { steps: 8 })
  await page.mouse.up()
  await page.waitForTimeout(250)
  const after = await label.boundingBox()
  expect(Math.hypot(after.x - before.x, after.y - before.y)).toBeGreaterThan(4)

  await modal.screenshot({ path: 'playwright-report/tt_cpd_scientific_review_definition.png' })

  const selects = modal.locator('select')
  await selects.nth(0).selectOption('dna_boundary_model')
  await expect(modal.getByText('tt-cpd-cis-syn · DNA boundary chain-b')).toBeVisible()
  await expect(modal.getByText(/1:O5' — 1:HO5'/)).toBeVisible()
  await expect(modal.getByText(/2:O3' — 2:HO3'/)).toBeVisible()
  await expect(modal.getByText('● phosphate boundary')).toBeVisible()
  await expect(modal.getByText('● glycosidic bonds')).toBeVisible()
  await expect(modal.getByText('Formal charge: -1')).toBeVisible()
  await modal.screenshot({ path: 'playwright-report/tt_cpd_scientific_review_boundary.png' })

  await selects.nth(0).selectOption('coupled_conformer')
  await expect(selects.nth(2)).toBeVisible()
  await selects.nth(1).selectOption('tt-cpd-trans-anti-ii')
  await selects.nth(2).selectOption('conformer-004')
  await expect(modal.getByText('tt-cpd-trans-anti-ii · conformer-004')).toBeVisible()
  await expect(modal.getByText(/Closest nonbonded:/)).toBeVisible()
  await expect(modal.getByText(/closest contact \d+\.\d+ Å/)).toBeVisible()
  await expect(selects.nth(3)).toBeVisible()
  await expect(selects.nth(3)).toHaveValue('training')

  await modal.screenshot({ path: 'playwright-report/tt_cpd_scientific_review_conformer.png' })
  await modal.getByPlaceholder('Reviewer name').fill('Jojo')
  await modal.getByPlaceholder(/Required: what you checked/).fill(
    'Request a revised conformer while retaining ordered atom identity.',
  )
  await modal.getByRole('button', { name: 'Revise' }).click()
  await expect(modal.getByRole('status')).toContainText('remains unresolved and gate-blocking')
  expect(savedDecision).toMatchObject({
    stage: 'coupled_conformer', product_id: 'tt-cpd-trans-anti-ii',
    conformer_id: 'conformer-004', decision: 'revise', partition: null,
  })
  expect(errors).toEqual([])
})
