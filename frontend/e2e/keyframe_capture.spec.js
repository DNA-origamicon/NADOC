import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Reads a legacy fixture; changes display metadata only in an isolated session.
// No saves/exports. Session cache is disabled; global teardown/reporter clean artifacts.
test('capture and duplicate preserve current overlays, pose, state and independent frames', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto('/?doc=__e2e__keyframe-capture&debug=1')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async example => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(example)
    document.getElementById('welcome-screen').classList.add('hidden')
    document.getElementById('left-panel').classList.remove('locked-hidden')
    for (const button of document.querySelectorAll('#left-tab-strip button')) button.disabled = false
    for (const id of ['right-panel', 'right-tab-strip']) document.getElementById(id).classList.remove('locked-inactive')
    window.__leftSidebar.refresh()
    const store = window.__nadocTest.store
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'strand', id: store.getState().currentDesign.strands[0].id }])
  }, path.resolve(process.cwd(), '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.locator('#zoom-volume-add').click()
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0]?.ready)).toBe(true)
  await page.locator('#view-volume-add-box').click()
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign.animations?.length)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js'), store = window.__nadocTest.store
    const d = store.getState().currentDesign
    const annotations = [{ id: 'shown-note', text: 'Shown', visible: true, refs: [{ kind: 'strand', id: d.strands[0].id }] },
      { id: 'hidden-note', text: 'Hidden', visible: false, refs: [{ kind: 'strand', id: d.strands[0].id }] }]
    const saved = await api.saveAnnotations({ annotations, enabled: true })
    store.setState({ currentDesign: { ...store.getState().currentDesign, annotations: saved.annotations, annotations_enabled: true } })
    await api.createKeyframe(d.animations[0].id, { name: 'Opening', text: 'Keep text', hold_duration_s: 2, transition_duration_s: 0 })
    await api.createKeyframe(d.animations[0].id, { name: 'Ending' })
  })
  const rows = page.locator('.anim-keyframe')
  await expect(rows).toHaveCount(2)
  await rows.first().getByRole('button', { name: 'Capture keyframe', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes[0].camera_pose_id)).toBeTruthy()
  const original = await page.evaluate(() => {
    const d = window.__nadocTest.store.getState().currentDesign, k = d.animations[0].keyframes[0]
    return { frame: k, pose: d.camera_poses.find(p => p.id === k.camera_pose_id), position: window.__NADOC_DBG__.camera.position.toArray(), count: d.feature_log.length }
  })
  expect(original.frame.annotation_ids).toEqual(['shown-note'])
  expect(original.frame.view_volume_ids).toHaveLength(1); expect(original.frame.zoom_volume_ids).toHaveLength(1)
  expect(original.pose.position).toEqual(original.position)
  expect(original.frame.feature_log_index).toBe(original.count ? original.count - 1 : -2)
  await rows.first().getByRole('button', { name: 'Duplicate keyframe', exact: true }).click()
  await expect(rows).toHaveCount(3)
  const frames = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes)
  expect(frames.map(k => k.name)).toEqual(['Opening', 'Opening', 'Ending'])
  expect(frames[1]).toEqual({ ...original.frame, id: frames[1].id }); expect(frames[1].id).not.toBe(frames[0].id)
  await page.locator('.zoom-volume-row [data-control="enabled"]').click()
  await expect(page.locator('.zoom-volume-inset')).toBeHidden()
  await rows.nth(1).getByRole('button', { name: 'Capture keyframe', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes[1].zoom_volume_ids)).toEqual([])
  const recaptured = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes)
  expect(recaptured[0]).toEqual(original.frame)
  expect(recaptured[1].camera_pose_id).not.toBe(original.frame.camera_pose_id)
  expect(recaptured[1].text).toBe('Keep text'); expect(recaptured[1].hold_duration_s).toBe(2)
  expect(errors, errors.join('\n')).toEqual([])
})
