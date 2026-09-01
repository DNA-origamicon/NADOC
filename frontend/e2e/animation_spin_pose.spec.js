import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000') + '/api'

test('keyframe pose and spin are independent controls', async ({ page }) => {
  test.setTimeout(45_000)
  const errors = trackConsoleErrors(page)
  const doc = `__e2e__animation-spin-pose-${Date.now()}`
  const headers = { 'X-NADOC-Doc': doc }
  await loadScaffoldedPart(page, { doc, name: 'animation-spin-pose' })
  await page.locator('.left-tab-btn[data-tab="scene"]').click()

  await page.locator('#camera-pose-capture-btn').click()
  await expect(page.locator('#camera-pose-list')).toContainText('Pose 1')

  await page.locator('#anim-actions-btn').click()
  await page.locator('#animation-new-btn').click()
  await expect(page.locator('#animation-select')).toHaveValue(/.+/)
  await page.locator('#animation-add-kf-btn').click()

  const pose = page.locator('[data-role="keyframe-pose"]')
  const spin = page.locator('[data-role="keyframe-spin-enabled"]')
  const controls = page.locator('.anim-kf-spin-controls')
  await expect(pose).toContainText('Pose 1')
  await pose.selectOption({ label: 'Pose 1' })
  await expect(spin).not.toBeChecked()
  await expect(controls).toBeHidden()

  await spin.check()
  await expect(controls).toBeVisible()
  await expect(pose).toHaveValue(/.+/)

  await expect.poll(async () => {
    const response = await page.request.get(`${API}/design`, { headers })
    const { design } = await response.json()
    const kf = design.animations[0].keyframes[0]
    return { pose: kf.camera_pose_id, axis: kf.spin_axis, rotations: kf.spin_rotations }
  }).toMatchObject({ pose: expect.any(String), axis: 'z', rotations: 1 })

  await spin.uncheck()
  await expect(controls).toBeHidden()
  await expect(pose).toHaveValue(/.+/)
  expect(errors, errors.join('\n')).toEqual([])
})
