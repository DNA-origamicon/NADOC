import { test, expect } from '@playwright/test'

async function openWelcomeWithPeers(page) {
  await page.route('**/api/collaboration/peers/status', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ peers: [
      { id: 'laptop', name: 'Lab laptop', online: true },
      { id: 'workstation', name: 'Remote workstation', online: false },
    ] }),
  }))
  await page.goto('/')
  await expect(page.locator('.lib-server-tab')).toHaveCount(3)
}

test('welcome library controls are spaced as actions, location tabs, and sort utilities', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openWelcomeWithPeers(page)

  const actions = page.locator('.lib-actions')
  const nav = page.locator('.lib-library-nav')
  const sortBar = page.locator('.lib-sort-bar')
  const toggle = page.locator('.lib-show-sim-folders')
  const tabs = page.locator('.lib-server-tab')

  await expect(toggle).toHaveText(/Show sim folders/)
  await expect(page.locator('.lib-trash-icon-btn')).toHaveAttribute('aria-label', 'Open Trash')
  await expect(tabs.first()).toHaveAttribute('aria-selected', 'true')
  await expect(tabs.nth(1)).toHaveAttribute('aria-selected', 'false')

  const [actionsBox, navBox, sortBox, toggleBox] = await Promise.all([
    actions.boundingBox(), nav.boundingBox(), sortBar.boundingBox(), toggle.boundingBox(),
  ])
  expect(actionsBox.y + actionsBox.height).toBeLessThanOrEqual(navBox.y)
  expect(toggleBox.y).toBeGreaterThanOrEqual(sortBox.y)
  expect(toggleBox.y + toggleBox.height).toBeLessThanOrEqual(sortBox.y + sortBox.height + 1)

  const tabBoxes = await tabs.evaluateAll(items => items.map(item => item.getBoundingClientRect().toJSON()))
  expect(new Set(tabBoxes.map(box => box.y)).size).toBe(1)
  expect(tabBoxes.every(box => box.height >= 28)).toBe(true)
})

test('welcome library navigation stacks cleanly on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 900 })
  await openWelcomeWithPeers(page)

  const sortBox = await page.locator('.lib-sort-bar').boundingBox()
  const toggleBox = await page.locator('.lib-show-sim-folders').boundingBox()
  expect(toggleBox.y).toBeGreaterThanOrEqual(sortBox.y)
  expect(toggleBox.y + toggleBox.height).toBeLessThanOrEqual(sortBox.y + sortBox.height + 1)
})

test('file management actions are discoverable by mouse and keyboard', async ({ page }) => {
  const now = new Date().toISOString()
  await page.route('**/api/library/files', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      { path: 'Parts', name: 'Parts', type: 'folder', size_bytes: 0, mtime_iso: now },
      { path: 'sample.nadoc', name: 'sample', type: 'part', size_bytes: 120, mtime_iso: now },
    ]),
  }))
  await page.route('**/api/collaboration/peers/status', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"peers":[]}',
  }))
  await page.goto('/')

  const folder = page.locator('[data-library-path="Parts"]')
  const file = page.locator('[data-library-path="sample.nadoc"]')
  await expect(folder).toBeVisible()
  await folder.click({ button: 'right' })
  await expect(page.locator('.lib-context-menu')).toContainText('Move to…')
  await expect(page.locator('.lib-context-menu')).toContainText('Move to Trash…')

  await file.click({ button: 'right' })
  await expect(page.locator('.lib-context-menu')).toContainText('Duplicate')
  await expect(page.locator('.lib-context-menu')).toContainText('Download')

  await file.focus()
  await file.press('Space')
  await expect(file).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.lib-bulk-actions')).toContainText('1 selected')
  await expect(page.locator('.lib-bulk-actions')).toContainText('Move to…')
  await expect(page.locator('.lib-bulk-actions')).toContainText('Trash')
})
