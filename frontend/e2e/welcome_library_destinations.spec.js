import { test, expect } from '@playwright/test'

// Metadata/network fixtures only. No workspace documents, downloads or stores.
const entry = (path, type) => ({ path, name: path, type, size_bytes: 120, mtime_iso: new Date().toISOString() })

test('Move to uses current validated folders rather than cached library entries', async ({ page }) => {
  await page.route('**/api/library/files', route => route.fulfill({ json: [
    entry('Stale', 'folder'), entry('md_jobs', 'folder'), entry('sample.nadoc', 'part'),
  ] }))
  let selectedPaths
  await page.route('**/api/library/move-destinations?**', route => {
    selectedPaths = new URL(route.request().url()).searchParams.getAll('path')
    return route.fulfill({ json: ['Valid', 'Valid/Nested'] })
  })
  let move
  await page.route('**/api/library/move', route => {
    move = route.request().postDataJSON()
    return route.fulfill({ json: { old_path: 'sample.nadoc', new_path: 'Valid/Nested/sample.nadoc' } })
  })
  await page.goto('/')
  const row = page.locator('[data-library-path="sample.nadoc"]')
  await row.hover()
  await row.getByTitle('Move', { exact: true }).click()
  await expect(page.locator('.lib-move-picker')).toBeVisible()
  expect(selectedPaths).toEqual(['sample.nadoc'])
  await expect(page.locator('[data-move-destination]')).toHaveCount(2)
  await expect(page.locator('[data-move-destination="Stale"]')).toHaveCount(0)
  await expect(page.locator('[data-move-destination="md_jobs"]')).toHaveCount(0)
  await page.locator('[data-move-destination="Valid/Nested"]').click()
  await expect.poll(() => move).toEqual({ path: 'sample.nadoc', dest_folder: 'Valid/Nested' })
})

test('the file list stays fixed when the initial refresh status disappears', async ({ page }) => {
  let releaseUsage
  const usageGate = new Promise(resolve => { releaseUsage = resolve })
  await page.route('**/api/library/files', route => route.fulfill({ json: [entry('sample.nadoc', 'part')] }))
  await page.route('**/api/jobs/active', route => route.fulfill({ json: { jobs: [] } }))
  await page.route('**/api/library/disk-usage', async route => {
    await usageGate
    await route.fulfill({ json: {} })
  })
  try {
    await page.goto('/')
    const status = page.locator('.lib-simulation-refresh-status')
    const tree = page.locator('.lib-tree')
    const file = page.locator('[data-library-path="sample.nadoc"]')
    await expect(file).toBeVisible()
    await expect(status).toBeVisible()
    const beforeTree = await tree.boundingBox()
    const beforeFile = await file.boundingBox()
    const reservedHeight = await status.evaluate(el => el.getBoundingClientRect().height)
    releaseUsage()
    await expect(status).toHaveCSS('visibility', 'hidden')
    expect((await tree.boundingBox()).y).toBeCloseTo(beforeTree.y, 1)
    expect((await file.boundingBox()).y).toBeCloseTo(beforeFile.y, 1)
    expect(await status.evaluate(el => el.getBoundingClientRect().height)).toBe(reservedHeight)
  } finally { releaseUsage() }
})
