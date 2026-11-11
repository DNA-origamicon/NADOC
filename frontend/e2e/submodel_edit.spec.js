import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

// Caller owns/removes isolated workspace and source link; no molecular authoring.
test('new and copied submodels accept mouse edits', async ({ page }, info) => {
  test.skip(!process.env.NADOC_SUBMODEL_ZOOM_SOURCE, 'Requires read-only source fixture')
  test.setTimeout(360000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const source = process.env.NADOC_SUBMODEL_ZOOM_SOURCE
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: source }, headers: route.request().headers() })
    await route.fulfill({ response })
  })
  await page.goto('/?debug=1&doc=__e2e__submodel-zoom&open=Submodel_tests.nadoc')
  await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_ZOOM_VOLUME__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30000 })
  for (const label of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const close = page.getByRole('button', { name: label, exact: true })
    if (await close.count()) await close.first().click()
  }
  await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.locator('#md-box-solvent-toggle').click()
  await expect(page.locator('#md-submodel-zoom')).toBeDisabled()
  expect(await page.locator('#md-box-solvent-body').evaluate(el => el.lastElementChild.id)).toBe('md-submodel')
  // Use the real wizard, without launching physical simulation.
  await page.locator('#md-define-submodel').click()
  await page.locator('#md-jobs-new-btn').click()
  const wizard = page.locator('.modal--wizard')
  await wizard.getByRole('button', { name: 'Next →', exact: true }).click()
  await wizard.getByRole('button', { name: 'Next →', exact: true }).click()
  const creating = page.waitForResponse(r => r.request().method() === 'POST' && /\/api\/md\/jobs$/.test(r.url()))
  await wizard.getByRole('button', { name: 'Create job', exact: true }).click()
  const response = await creating
  expect(response.ok()).toBe(true)
  const job = await response.json()
  await expect(wizard).toBeHidden()
  await page.locator('#md-define-submodel').click()
  let currentId = job.job_id
  const saved = async id => (await (await page.request.get(`/api/md/jobs/${id}/submodel`)).json()).box
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ target: [8,2,14.5], position: [40,12,40] }))
  await page.waitForTimeout(1000)
  for (const kind of ['new', 'copy', 'legacy-copy', 'existing-pathless-copy']) {
    const sourceBox = kind === 'new' ? null : await saved(job.job_id)
    if (kind !== 'new') {
      if (kind === 'legacy-copy') {
        const file = path.join(process.env.NADOC_WORKSPACE, 'md_jobs', job.job_id, 'job.json')
        const metadata = JSON.parse(fs.readFileSync(file, 'utf8'))
        metadata.prep_params.design_source_path = null // Existing jobs can store the path only on the job.
        fs.writeFileSync(file, JSON.stringify(metadata))
      }
      await page.locator(`[data-job-id="${job.job_id}"]:visible`).first().click({button:'right'})
      const copying = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/md/jobs/${job.job_id}/copy`))
      await page.getByText('Copy job (new seed)', {exact:true}).click()
      const copiedResponse = await copying
      expect(copiedResponse.ok()).toBe(true)
      const copied = (await copiedResponse.json()).job
      currentId = copied.job_id
      expect(copied.design_source_path).toBe('Submodel_tests.nadoc')
      await expect.poll(() => page.evaluate(() => window.__nadocMdPanel.getSelectedJob()?.job_id)).toBe(currentId)
      if (kind === 'existing-pathless-copy') {
        const file = path.join(process.env.NADOC_WORKSPACE, 'md_jobs', currentId, 'job.json')
        const metadata = JSON.parse(fs.readFileSync(file, 'utf8'))
        metadata.design_source_path = null
        metadata.prep_params.design_source_path = null
        // Match the user's legacy copy: prepared-source ownership survives even
        // when its path is lost. Unprepared wizard drafts have no revision yet.
        metadata.project_id = JSON.parse(fs.readFileSync(source, 'utf8')).id
        fs.writeFileSync(file, JSON.stringify(metadata))
      }
      await page.locator('#md-define-submodel').click()
    }
    const before = await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0])
    const center = await page.evaluate(() => window.__NADOC_SUBMODEL__.centers()[0])
    await page.mouse.move(center.x, center.y)
    await page.mouse.down()
    expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.isDragging())).toBe(true)
    await page.evaluate(() => window.__nadocMdPanel.refresh())
    await page.mouse.move(center.x+45, center.y+25, {steps:15})
    await page.mouse.up()
    await page.waitForTimeout(1000)
    expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.selected())).toBe('submodel')
    expect(await page.evaluate(() => window.__nadocMdPanel.getSelectedJob()?.job_id)).toBe(currentId)
    const moved = await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0])
    expect(moved.min_corner).not.toEqual(before.min_corner)
    await expect(page.locator('#md-submodel > [role=status]')).toHaveText('Submodel saved to job.')
    await expect.poll(async () => (await saved(currentId)).min_corner).toEqual(moved.min_corner)
    await page.locator('#md-submodel-shell').fill('2.7')
    await page.locator('#md-submodel-shell').press('Tab')
    await expect.poll(async () => (await saved(currentId)).shell_nm).toBe(2.7)
    if (kind === 'new' || kind === 'legacy-copy') {
      for (const mode of ['scale', 'rotate']) {
        await page.locator(`#md-submodel [data-volume-tool="${mode}"]`).click()
        const beforeMode = await saved(currentId)
        // Read screen coordinates from the real gizmo; all manipulation is mouse input.
        const handle = await page.evaluate(mode => {
          const tc = window.__nadocTest.scene.children.find(o => o.controls?.object?.userData?.volumeId === 'submodel').controls
          tc.getHelper().updateMatrixWorld(true)
          const mesh = tc._gizmo.gizmo[mode].children.find(o => o.name === (mode === 'scale' ? 'X' : 'E') && (mode !== 'scale' || o.geometry.type === 'BoxGeometry'))
          const point = tc.object.position.clone()
          if (mode === 'scale') { mesh.geometry.computeBoundingBox(); mesh.geometry.boundingBox.getCenter(point) }
          else point.fromBufferAttribute(mesh.geometry.attributes.position, 0)
          mesh.localToWorld(point); point.project(tc.camera)
          const rect = document.querySelector('#canvas').getBoundingClientRect()
          return { x: rect.left + (point.x + 1) * rect.width / 2, y: rect.top + (1 - point.y) * rect.height / 2 }
        }, mode)
        await page.mouse.move(handle.x, handle.y)
        console.log('HANDLE', kind, mode, handle)
        await page.mouse.down()
        if (!(await page.evaluate(() => window.__NADOC_SUBMODEL__.isDragging()))) {
          await page.screenshot({path:info.outputPath('missed-handle.png')})
          console.log('REVIEW_IMAGE', info.outputPath('missed-handle.png'))
          await page.waitForTimeout(20000)
        }
        expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.isDragging())).toBe(true)
        await page.mouse.move(handle.x + 25, handle.y - 30, {steps:12})
        await page.mouse.up()
        await expect.poll(async () => mode === 'scale' ? (await saved(currentId)).max_corner : (await saved(currentId)).rotation)
          .not.toEqual(mode === 'scale' ? beforeMode.max_corner : beforeMode.rotation)
        expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.selected())).toBe('submodel')
      }
      await page.locator('#md-submodel [data-volume-tool="translate"]').click()
    }
    const persisted = await saved(currentId)
    // Switch away and back through the public panel, and check actual disk/API state.
    await page.evaluate(async id => {
      window.__nadocMdPanel.deselectJob()
      await window.__nadocMdPanel.selectJob(id)
    }, currentId)
    await page.locator('#md-define-submodel').click()
    expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0].min_corner)).toEqual(persisted.min_corner)
    if (sourceBox) expect(await saved(job.job_id)).toEqual(sourceBox)
    console.log('VERIFIED', kind, currentId, JSON.stringify(persisted))

  }
  const finalBox = await saved(currentId)
  await page.goto('/?debug=1&doc=__e2e__submodel-zoom&open=Submodel_tests.nadoc')
  await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_SUBMODEL__)
  await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  const reopenedRow = page.locator(`[data-job-id="${currentId}"]:visible`).first()
  await expect(reopenedRow).toBeVisible({timeout:30000})
  await reopenedRow.click()
  if (!(await page.locator('#md-define-submodel').isVisible())) await page.locator('#md-box-solvent-toggle').click()
  await page.locator('#md-define-submodel').click()
  await expect.poll(() => page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0]?.min_corner)).toEqual(finalBox.min_corner)
  await expect(page.locator('#md-submodel-shell')).toHaveValue('2.7')
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ target: [8,2,14.5], position: [40,12,40] }))
  for (const label of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const close = page.getByRole('button', { name: label, exact: true })
    if (await close.count()) await close.first().click()
  }
  await page.screenshot({path:info.outputPath('edit.png')})
  console.log('REVIEW_IMAGE',info.outputPath('edit.png'))
  await page.waitForTimeout(20000)
})
