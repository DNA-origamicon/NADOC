import { test, expect } from '@playwright/test'

// Only listing metadata and HTTP replies are mocked: no structures, downloads,
// workspace files, or project/session stores are authored by these checks.
async function openLibrary(page) {
  let path = 'sample.nadoc'
  let renameCalls = 0
  let openCalls = 0
  let failure = null
  await page.route('**/api/library/files', route => route.fulfill({ json: [
    { path, name: path, type: 'part', size_bytes: 120, mtime_iso: new Date().toISOString() },
    { path: 'taken.nadoc', name: 'taken', type: 'part', size_bytes: 120, mtime_iso: new Date().toISOString() },
  ] }))
  await page.route('**/api/library/disk-usage', async route => {
    await new Promise(resolve => setTimeout(resolve, 1200))
    await route.fulfill({ json: { [path]: 42 } })
  })
  await page.route('**/api/library/open-part', route => {
    openCalls++
    return route.fulfill({ status: 404, json: { detail: 'Test metadata only' } })
  })
  await page.route('**/api/library/rename', async route => {
    renameCalls++
    if (failure) return route.fulfill({ status: 403, json: { detail: failure } })
    const old = path
    path = route.request().postDataJSON().new_name
    await route.fulfill({ json: { old_path: old, new_path: path } })
  })
  await page.goto('/')
  const row = page.locator('[data-library-path="sample.nadoc"]')
  await row.focus()
  await row.press('F2')
  const input = row.locator('input')
  await expect(input).toBeFocused()
  await expect(input).toHaveValue('sample')
  return { input, row, counts: () => ({ renameCalls, openCalls }), fail: message => { failure = message } }
}

test('rename survives typing spaces, select-all, clicks and late disk-usage replies', async ({ page }) => {
  const { input, counts } = await openLibrary(page)
  await input.fill('new')
  await input.press('End')
  await input.press('Space')
  await input.pressSequentially('name', { delay: 250 })
  await expect(input).toHaveValue('new name')
  await expect(input).toBeFocused()
  await input.click()
  await input.press('ControlOrMeta+a')
  await expect(input).toHaveValue('new name')
  await input.press('Enter')
  await expect(page.locator('[data-library-path="new name.nadoc"]')).toBeVisible()
  await expect(page.locator('.lib-rename-editor')).toHaveCount(0)
  expect(counts()).toEqual({ renameCalls: 1, openCalls: 0 })
})

test('real collisions and server errors retain the draft; mouse confirmation retries successfully', async ({ page }) => {
  const { input, row, counts, fail } = await openLibrary(page)
  await input.fill('taken')
  await input.press('Enter')
  await expect(input).toBeFocused()
  expect(counts().renameCalls).toBe(0)
  fail('Workspace is read-only')
  await input.fill('available')
  await row.getByTitle('Confirm rename', { exact: true }).click()
  await expect(page.getByText('Workspace is read-only', { exact: true }).last()).toBeVisible()
  await expect(input).toHaveValue('available')
  await expect(input).toBeFocused()
  fail(null)
  await row.getByTitle('Confirm rename', { exact: true }).click()
  await expect(page.locator('[data-library-path="available.nadoc"]')).toBeVisible()
  expect(counts()).toEqual({ renameCalls: 2, openCalls: 0 })
})


test('click-away saves, Cancel discards, and rename buttons align beside the input', async ({ page }) => {
  const { input, row, counts } = await openLibrary(page)
  for (const width of [1280, 420]) {
    await page.setViewportSize({ width, height: 900 })
    const inputBox = await input.boundingBox()
    const okBox = await row.getByTitle('Confirm rename', { exact: true }).boundingBox()
    const cancelBox = await row.getByTitle('Cancel', { exact: true }).boundingBox()
    expect(okBox.x - (inputBox.x + inputBox.width)).toBeGreaterThanOrEqual(0)
    expect(okBox.x - (inputBox.x + inputBox.width)).toBeLessThanOrEqual(6)
    expect(Math.abs(okBox.y + okBox.height / 2 - inputBox.y - inputBox.height / 2)).toBeLessThan(1)
    expect(Math.abs(cancelBox.y + cancelBox.height / 2 - inputBox.y - inputBox.height / 2)).toBeLessThan(1)
  }
  await input.fill('saved on blur')
  await page.locator('.lib-search-input').click()
  const renamed = page.locator('[data-library-path="saved on blur.nadoc"]')
  await expect(renamed).toBeVisible()
  await expect(page.locator('.lib-rename-editor')).toHaveCount(0)
  expect(counts()).toEqual({ renameCalls: 1, openCalls: 0 })
  await renamed.focus()
  await renamed.press('F2')
  await renamed.locator('input').fill('discard')
  await renamed.getByTitle('Cancel', { exact: true }).click()
  await expect(page.locator('.lib-rename-editor')).toHaveCount(0)
  expect(counts()).toEqual({ renameCalls: 1, openCalls: 0 })
  await expect(renamed).toBeVisible()
})
