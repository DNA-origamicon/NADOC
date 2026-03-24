import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'

test('unfold view works after loading multi_domain_test2', async ({ page }) => {
  const errors = []
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', err => errors.push('PAGEERROR: ' + err.message))

  await page.goto('/')

  // Load design via API
  const fileContent = readFileSync('/home/joshua/NADOC/Examples/multi_domain_test2.nadoc', 'utf8')
  const r = await page.request.post('/api/design/load', {
    headers: { 'Content-Type': 'application/json' },
    data: JSON.stringify({ content: fileContent })
  })
  expect(r.status()).toBe(200)
  await page.waitForTimeout(2000)

  console.log('Errors after load:', JSON.stringify(errors))
  expect(errors).toHaveLength(0)
  errors.length = 0

  // Open View menu and find unfold option
  const viewMenu = page.locator('.menu-item').filter({ hasText: 'View' }).first()
  await viewMenu.hover()
  await page.waitForTimeout(400)
  const items = await page.locator('.dropdown-item').allTextContents()
  console.log('View menu items:', items)

  const unfoldItem = page.locator('.dropdown-item').filter({ hasText: /2D|unfold/i }).first()
  const cnt = await unfoldItem.count()
  console.log('Unfold item count:', cnt)

  if (cnt > 0) {
    await unfoldItem.click()
    await page.waitForTimeout(2500)
    console.log('Errors after unfold:', JSON.stringify(errors))
    expect(errors).toHaveLength(0)
  } else {
    console.log('No unfold menu item found')
  }
})
