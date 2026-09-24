import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('editor selections and period pings render in the guest and clear on deselection', async ({ page, context }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__shared_selection', name: 'shared_selection' })
  const guest = await context.newPage(), guestErrors = trackConsoleErrors(guest)
  await guest.goto('/viewer.html?test=1')
  async function publish() {
    const bytes = await page.evaluate(async () => {
      const { capturePresentationSelection } = await import('/src/scene/presentation_selection.js')
      const { prepareScene } = await import('/src/viewer/prepared_scene.js')
      const scene = window.__nadocTest.scene, selection = capturePresentationSelection(scene)
      const position = selection ? scene.getObjectByProperty('uuid', selection.target).geometry.attributes.position : null
      const target = position?.count ? [position.getX(0), position.getY(0), position.getZ(0)] : [0,0,0]
      const camera = { position: [target[0]+15,target[1]+10,target[2]+35], target, up: [0,1,0], fov: 55, orbitMode: 'orbit' }
      window.__nadocTest.applyCameraPoseForTest(camera)
      return Array.from(new Uint8Array(prepareScene({ scene, camera, view: { selection } })))
    })
    await guest.evaluate(async bytes => {
      if (!await window.__preparedViewer.loadFile(new File([new Uint8Array(bytes)], 'selection.nadocview'))) throw new Error(document.getElementById('status').textContent)
    }, bytes)
  }
  for (const kind of ['base', 'domain', 'strand']) {
    await page.evaluate(kind => {
      const s = window.__nadocTest.store, state = s.getState(), nuc = state.currentGeometry.find(n => n.strand_id)
      const ref = kind === 'base' ? { kind, key: `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}` } : kind === 'domain' ? { kind, strandId: nuc.strand_id, domainIndex: nuc.domain_index ?? 0 } : { kind, id: nuc.strand_id }
      s.setState({ selection: { ...state.selection, items: [ref], primary: ref } })
    }, kind)
    await publish()
    await expect(guest.locator('.shared-selection-label')).toContainText(new RegExp(kind, 'i'))
  }
  await expect(page.locator('[data-selection-ping]')).toBeEnabled()
  await page.bringToFront()
  await page.evaluate(() => document.activeElement?.blur())
  await page.keyboard.press('.')
  await expect.poll(() => page.evaluate(async () => { const { capturePresentationSelection } = await import('/src/scene/presentation_selection.js'); return !!capturePresentationSelection(window.__nadocTest.scene)?.ping })).toBe(true)
  await expect(page.locator('#canvas-area > .selection-ping')).toBeVisible()
  await publish()
  await expect(guest.locator('main > .selection-ping')).toBeVisible()
  await expect(guest.locator('main > .selection-ping')).toBeHidden({ timeout: 5000 })
  // The same event must not replay when an unrelated scene refresh arrives.
  await publish(); await expect(guest.locator('main > .selection-ping')).toBeHidden()
  await page.locator('[data-selection-ping]').evaluate(button => button.click())
  await publish(); await expect(guest.locator('main > .selection-ping')).toBeVisible()
  await page.evaluate(() => { const s = window.__nadocTest.store; s.setState({ selection: { ...s.getState().selection, items: [], primary: null } }) })
  await publish()
  await expect(guest.locator('.shared-selection-label')).toBeHidden()
  await expect(guest.locator('main > .selection-ping')).toBeHidden()
  await expect(page.locator('[data-selection-ping]')).toBeDisabled()
  expect(errors).toEqual([]); expect(guestErrors).toEqual([])
})
