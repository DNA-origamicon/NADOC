import { test, expect } from '@playwright/test'

test('clearing welcome search restores the previous folder expansion', async ({ page }) => {
  const paths = [
    ['Alpha', 'folder'], ['Alpha/Nested', 'folder'],
    ['Alpha/Nested/match.nadoc', 'part'], ['Alpha/match.nadoc', 'part'],
    ['Beta', 'folder'], ['Beta/match.nadoc', 'part'],
  ]
  await page.route('**/api/library/files', route => route.fulfill({
    json: paths.map(([path, type]) => ({ path, type, name: path.split('/').pop(), size_bytes: 10 })),
  }))
  await page.route('**/api/collaboration/peers/status', route => route.fulfill({ json: { peers: [] } }))
  await page.goto('/')
  const row = path => page.locator(`[data-library-path="${path}"]`)
  const toggle = path => row(path).locator('.lib-folder-toggle')
  const search = page.locator('.lib-search-input')
  await row('Alpha').click()
  await expect(toggle('Alpha/Nested')).toHaveText('▶')

  await search.fill('match')
  await expect(row('Beta/match.nadoc')).toBeVisible()
  await expect(row('Alpha/Nested/match.nadoc')).toBeVisible()
  await search.fill('no matches here')
  await expect(page.locator('.lib-empty')).toBeVisible()
  await search.fill('match')
  await search.fill('')
  await expect(toggle('Alpha')).toHaveText('▼')
  await expect(toggle('Alpha/Nested')).toHaveText('▶')
  await expect(toggle('Beta')).toHaveText('▶')
  await expect(row('Alpha/match.nadoc')).toBeVisible()
  await expect(row('Beta/match.nadoc')).toBeHidden()
  await expect(row('Alpha/Nested/match.nadoc')).toBeHidden()

  // Each new search snapshots the current state, including nested expansion.
  await row('Alpha/Nested').click()
  await row('Alpha').click()
  await search.fill('match')
  await search.fill('   ')
  await expect(toggle('Alpha')).toHaveText('▶')
  await row('Alpha').click()
  await expect(toggle('Alpha/Nested')).toHaveText('▼')
  await expect(toggle('Beta')).toHaveText('▶')
})
