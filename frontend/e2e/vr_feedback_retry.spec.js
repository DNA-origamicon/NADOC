import { test, expect } from '@playwright/test'

// No saved designs: empty isolated document, session caching disabled. All native
// VR requests are intercepted; no physical viewer or sidecars are touched.
test('failed native feedback is retried by the browser without another edit', async ({ page }) => {
  const attempts = []
  await page.route('**/api/vr/**', route => route.fulfill({ json: { running: false } }))
  await page.route('**/api/vr/ligation-ends', async route => {
    attempts.push(route.request().postDataJSON())
    await route.fulfill({ status: attempts.length === 1 ? 503 : 200, json: attempts.length === 1 ? { detail: 'temporary transport failure' } : { published: true } })
  })
  await page.goto('/?test=1&doc=__e2e__vr-feedback')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const { createVRLigation } = await import('/src/scene/vr_ligation.js')
    const tool = createVRLigation({ getState: store.getState, api })
    await tool.publish(); await tool.publish(); await tool.publish()
  })
  expect(attempts).toHaveLength(2)
  expect(attempts[1]).toEqual(attempts[0])
})
