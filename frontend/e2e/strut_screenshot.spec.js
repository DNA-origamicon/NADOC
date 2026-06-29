// Troubleshooting-only: load the user's 2x2_strutted_corner design and screenshot
// the strut region so we can SEE the rendered overhang duplex (not just numbers).
import { test, expect } from '@playwright/test'
import path from 'node:path'

const API_BASE = process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8001'

const DESIGN = process.env.STRUT_DESIGN || '2x2_strutted_corner'
const OUT = process.env.STRUT_OUT || 'strut_as_saved'

test('screenshot strut corner', async ({ page, request }) => {
  test.setTimeout(120_000)
  const designPath = path.resolve(process.cwd(), '..', 'workspace', `${DESIGN}.nadoc`)
  const loadResp = await request.post(`${API_BASE}/api/design/load`, { data: { path: designPath } })
  expect(loadResp.status(), 'failed to load design').toBe(200)

  await page.goto('/')
  await expect(page.locator('#canvas')).toBeVisible()
  // Open the design from the welcome-screen file list so the editor actually renders it.
  await page.getByText(DESIGN, { exact: false }).first().dblclick()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(3000)   // geometry round-trip + render

  // Zoom in toward the structure centre (OrbitControls wheel) so the small strut
  // duplex fills the frame.
  const box = await page.locator('#canvas').boundingBox()
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2
  await page.mouse.move(cx, cy)
  for (let i = 0; i < 18; i++) {
    await page.mouse.wheel(0, -120)
    await page.waitForTimeout(40)
  }
  await page.waitForTimeout(600)
  await page.screenshot({ path: `e2e/screenshots/${OUT}.png`, fullPage: false })
})
