import { expect, test } from '@playwright/test'

const DESIGN = 'graphene only'

async function openGraphene(page) {
  await page.goto('/?doc=__e2e__graphene-animation-ions')
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN}$`) }).first()
  await row.waitFor({ state: 'visible', timeout: 60_000 })
  await row.click()
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
}

function visibleIons() {
  let n = 0
  window.__nadocScene?.traverse?.(object => {
    if (object.visible && /^ion\d+$/.test(object.userData?.solventKey || '')) n += object.count || 0
  })
  return n
}

test('graphene-only trajectory exposes numeric bounds and both video exporters render ions', async ({ page }) => {
  test.setTimeout(300_000)
  await openGraphene(page)
  await page.locator('.left-tab-btn[data-tab="scene"]').click()

  const start = page.locator('[data-role="trajectory-frame-start"]')
  const end = page.locator('[data-role="trajectory-frame-end"]')
  await expect(start).toHaveValue('0', { timeout: 30_000 })
  await expect(end).toHaveValue('119')
  // Commit the existing values to exercise manual entry without changing the user's
  // real workspace fixture (the E2E backend serves that file read/write).
  await start.fill('0'); await start.press('Enter')
  await end.fill('119'); await end.press('Enter')

  // Keep each proof short while still crossing several exported frames.
  await page.locator('#anim-export-fps').fill('1')
  const regularDownload = page.waitForEvent('download', { timeout: 180_000 })
  const regularIons = expect.poll(() => page.evaluate(visibleIons), { timeout: 180_000 }).toBeGreaterThan(0)
  await page.locator('#anim-export-btn').click()
  await Promise.all([regularDownload, regularIons])

  await page.locator('#photo-tab-btn').click()
  await page.locator('#photo-video-res').selectOption('720p')
  await page.locator('#photo-video-fps').fill('1')
  const photoDownload = page.waitForEvent('download', { timeout: 180_000 })
  const photoIons = expect.poll(() => page.evaluate(visibleIons), { timeout: 180_000 }).toBeGreaterThan(0)
  await page.locator('#photo-video-btn').click()
  await Promise.all([photoDownload, photoIons])
})
