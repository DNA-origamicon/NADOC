import { test, expect } from '@playwright/test'
import fs from 'node:fs'

// Opt-in real prepared specimen. No mocked job endpoints. Caller supplies an
// isolated copy of the experiment workspace and deletes it in a finally block.
// Writes settings only in the caller's disposable job copy; source is read-only.
test('headlessly saved duplex submodel is visible after reopening its job', async ({ page }, info) => {
  test.skip(!process.env.NADOC_SUBMODEL_MANIFEST, 'Requires prepared native experiment')
  test.setTimeout(60_000)
  const manifest = JSON.parse(fs.readFileSync(process.env.NADOC_SUBMODEL_MANIFEST, 'utf8'))
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?doc=e2e-submodel-duplex')
  await page.waitForFunction(() => window.__NADOC_SUBMODEL__ && window.__nadocTest)
  await page.evaluate(async source => {
    const api = await import('/src/api/client.js')
    if (!(await api.loadDesign(source))) throw new Error('Duplex load failed')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.querySelectorAll('#left-tab-strip button').forEach(b => { b.disabled = false })
    window.__leftSidebar?.refresh?.()
  }, manifest.source)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('#engine-selector-mount').getByRole('tab', { name: 'oxDNA', exact: true }).click()
  if (manifest.display_relaxed) {
    // API-only source loading does not set the file-browser workspace handle.
    // Drive the same display controller directly for this headless review.
    await page.evaluate(async id => {
      const result = await window.__nadocOxdnaDisplay.displayJob(id, true)
      if (!result.ok) throw new Error(`Relaxed display failed: ${result.reason}`)
    }, manifest.job_id)
    await expect.poll(() => page.evaluate(() => window.__nadocOxdnaDisplay?.mode())).toBe('relaxed')
  }
  await page.evaluate(async ({ id, camera }) => {
    await window.__NADOC_SUBMODEL__.selectJob('oxdna', id)
    window.__nadocTest.applyCameraPoseForTest(camera ?? { position: [2, -25, 7], target: [2, 1, 7], up: [0, 0, 1] })
  }, { id: manifest.job_id, camera: manifest.camera })
  const box = await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0])
  expect(box.min_corner).toEqual(manifest.selection.box.min_corner)
  expect(box.max_corner).toEqual(manifest.selection.box.max_corner)
  expect(box.rotation).toEqual(manifest.selection.box.rotation)
  const radius = page.locator('#oxdna-submodel-shell')
  const shellRadius = manifest.selection.box.shell_nm ?? 3
  await radius.fill(String(shellRadius))
  await radius.dispatchEvent('change')
  await expect.poll(() => page.evaluate(() => window.__NADOC_SUBMODEL__.shellVisible())).toBe(true)
  await page.locator('#oxdna-submodel-visible').uncheck()
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.shellVisible())).toBe(false)
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0].outline_visible)).toBe(false)
  await page.screenshot({ path: info.outputPath('duplex-hidden.png') })
  await page.locator('#oxdna-submodel-visible').check()
  await expect(page.locator('#oxdna-submodel > p[role=status]')).toHaveText('Submodel saved to job.')
  const saved = await page.evaluate(async id => {
    const api = await import('/src/api/client.js')
    return await api.getSimulationSubmodel('oxdna',id)
  }, manifest.job_id)
  expect(saved.box.shell_nm).toBe(shellRadius)
  expect(saved.box.visible).toBe(true)
  const buttonStyle = await page.locator('#oxdna-define-submodel').evaluate(button => {
    const reference = document.createElement('button')
    reference.className = 'btn btn--sm'
    button.parentElement.append(reference)
    const keys = ['backgroundColor', 'color', 'borderRadius', 'borderTopColor', 'paddingLeft', 'height']
    const actual = Object.fromEntries(keys.map(k => [k, getComputedStyle(button)[k]]))
    const expected = Object.fromEntries(keys.map(k => [k, getComputedStyle(reference)[k]]))
    reference.remove()
    return { actual, expected }
  })
  expect(buttonStyle.actual).toEqual(buttonStyle.expected)
  await page.locator('#oxdna-define-submodel').click()
  const point = await page.evaluate(() => window.__NADOC_SUBMODEL__.outlinePoint('submodel'))
  expect(point.x).toBeGreaterThan(0)
  expect(point.y).toBeGreaterThan(0)
  await page.keyboard.press('Escape')
  await page.mouse.click(point.x, point.y)
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.selected())).toBe('submodel')
  await page.keyboard.press('Escape')
  await expect(page.locator('#oxdna-submodel > button').nth(1)).toBeHidden()
  await page.locator('#oxdna-define-submodel').evaluate(button => button.blur())
  await page.screenshot({ path: info.outputPath('duplex-box.png') })
  if (manifest.inspect_visualizations) {
    await page.evaluate(() => {
      const all = document.getElementById('oxdna-jobs-show-all')
      all.checked = true; all.dispatchEvent(new Event('change'))
    })
    await expect.poll(() => page.evaluate(id => !!document.querySelector('#oxdna-jobs-list [data-job-id="' + id + '"]'), manifest.job_id)).toBe(true)
    await page.evaluate(id => document.querySelector('#oxdna-jobs-list [data-job-id="' + id + '"]').click(), manifest.job_id)
    await page.locator('#oxdna-jobs-viz-toggle').scrollIntoViewIfNeeded()
    const options = await page.locator('input[name="oxdna-viz"]').evaluateAll(inputs => inputs.map(i => ({
      value: i.value, disabled: i.disabled, label: i.parentElement.textContent.trim(),
    })))
    fs.writeFileSync(info.outputPath('visualization-options.json'), JSON.stringify(options, null, 2))
    expect(options.map(o => o.value)).toEqual(expect.arrayContaining(['display','flex','deviation','strain','traj','traj-full','occupancy']))
    if (manifest.display_relaxed) {
      await expect(page.locator('#oxdna-submodel-projection')).toContainText('simulation VRAM 0 MiB')
      for (const value of ['display', 'flex', 'deviation', 'strain', 'traj', 'traj-full', 'occupancy']) {
        const radio = page.locator('input[name="oxdna-viz"][value="' + value + '"]')
        if (await radio.isDisabled()) continue // Availability follows the normal job type.
        await radio.check()
        await expect(radio).toBeChecked()
        const expectedMode = { display: 'relaxed', flex: 'rmsf', deviation: 'deviation', strain: 'strain', traj: 'trajectory', 'traj-full': 'trajectory', occupancy: 'occupancy' }[value]
        await expect.poll(() => page.evaluate(() => window.__nadocOxdnaDisplay.mode())).toBe(expectedMode)
        await page.screenshot({ path: info.outputPath('duplex-mode-' + value + '.png') })
      }
    }
    await page.locator('#oxdna-jobs-traj-full-toggle').scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath('duplex-options.png') })
    await page.locator('#oxdna-jobs-occupancy-toggle').scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath('duplex-occupancy.png') })
  }
  await page.locator('#engine-selector-mount').getByRole('tab', { name: 'NAMD', exact: true }).click()
  await page.locator('#md-box-solvent-toggle').click()
  await page.locator('#md-define-submodel').click()
  await expect(page.locator('#md-box-view-details')).toBeChecked()
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.shellVisible())).toBe(true)
  await page.locator('#md-box-view-details').uncheck()
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.shellVisible())).toBe(false)
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0].outline_visible)).toBe(false)
  expect(errors).toEqual([])
})
