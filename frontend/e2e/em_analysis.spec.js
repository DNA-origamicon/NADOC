import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import { createHash } from 'node:crypto'

// Existing design is read-only. File > New establishes an empty __e2e__ editor
// host through the public operation; global teardown removes its autosave/history.
// No downloads or simulation jobs are created.
// Dedicated Playwright servers disable session persistence. Browser cache is an
// ephemeral Playwright context; screenshots/traces use its cleaned output directory.
const source = fileURLToPath(new URL('../../workspace/Plasmonic_test.nadoc',import.meta.url))
const digest = async () => createHash('sha256').update(await readFile(source)).digest('hex')

test('520 nm EM map on the existing plasmonic design, slices and cleanup', async ({ page }) => {
  // Native DNA rendering under software WebGL can dominate the two EM solves.
  test.setTimeout(240000)
  const before = await digest(), errors = []
  const design = JSON.parse(await readFile(source, 'utf8'))
  const [a, b] = design.nanoparticles
  const gap = Math.hypot(...[3, 7, 11].map(i => a.pose.values[i] - b.pose.values[i]))
    - (a.diameter_nm + b.diameter_nm) / 2
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    const expectedRejection = message.location().url?.endsWith('/api/em-analysis/solve') && message.text().includes('422')
    if (message.type() === 'error' && !message.location().url?.endsWith('favicon.ico') && !expectedRejection) errors.push(message.text())
  })
  // Suppress workspace autosave: the source is a read-only visualization input.
  await page.route('**/api/design/save-workspace', route => route.fulfill({json:{identity_disposition:'confirmed'}}))
  await page.setViewportSize({ width: 1500, height: 950 })
  try {
    await page.addInitScript(()=>Object.defineProperty(window,'devicePixelRatio',{get:()=>.5}))
    await page.goto('/')
    await page.waitForFunction(() => !!window.__nadocTest)
    await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
    await page.locator('#menu-file-new').click()
    await page.fill('#new-design-name', '__e2e__em-analysis-host')
    await page.getByRole('button', {name:'Create',exact:true}).click()
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
    const loaded = await page.evaluate(async file => {
      const api = await import('/src/api/client.js')
      return Boolean(await api.loadDesign(file))
    }, source)
    expect(loaded).toBe(true)
    await page.waitForFunction(() => window.__nadocTest.nanoparticles.rendered().length === 2)
    await page.evaluate(()=>window.__nadocTest.setRepresentation('cylinders'))
    await page.evaluate(() => {
      const { camera, controls } = window.__nadocTest
      controls.target.set(9, 16, 26); camera.position.set(105, 85, 125); controls.update()
    })
    for(const instance of await page.evaluate(()=>window.__rightSidebar.getInstances()))await page.evaluate(id=>window.__rightSidebar.close(id),instance.id)
    await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
    await page.locator('.submenu-item').filter({ hasText: 'Nanoparticles' }).first().hover()
    await page.locator('#menu-tools-em-analysis').click()
    const panel = page.locator('#em-analysis-panel')
    await expect(panel).toBeVisible()
    await expect(panel.locator('[data-solver]')).toHaveValue('multipole')
    await expect(panel.locator('[data-shell]')).toHaveValue('ssdna_wlc')
    await expect(panel.locator('[data-sampling]')).toHaveValue('field_adaptive')
    await panel.locator('[data-resolution]').selectOption('25')
    const rejection = page.waitForResponse(response => response.url().endsWith('/api/em-analysis/solve') && response.status() === 422)
    await panel.locator('[data-run]').click()
    expect((await (await rejection).json()).detail).toContain('DNA dielectric shells overlap or touch')
    await expect(panel.locator('[data-status]')).toContainText('DNA dielectric shells overlap or touch')
    await expect(panel.locator('[data-status]')).toContainText(`${gap.toFixed(2)} nm metal gap`)
    await expect(panel.locator('[data-shell]')).toHaveValue('ssdna_wlc')
    await expect(panel.locator('[data-download]')).toBeDisabled()
    await panel.locator('[data-bare-retry]').click()
    await expect(panel.locator('[data-shell]')).toHaveValue('none')
    await expect(panel.locator('[data-status]')).toContainText('Sampled peak', { timeout: 60000 })
    await expect(panel.locator('[data-status]')).toContainText(`${gap.toFixed(2)} nm`)
    await expect(panel.locator('[data-download]')).toBeEnabled()
    await panel.locator('[data-dot-size]').fill('6')
    await expect(panel.locator('[data-dot-size-value]')).toHaveText('6 px')
    expect(await page.evaluate(() => window.__nadocTest.scene.getObjectByName('experimental-em-field')?.children.find(object => object.isPoints)?.material.size)).toBe(6)
    await expect(panel.locator('[data-download]')).toBeEnabled()
    await expect(panel.locator('[data-status]')).toContainText('close-gap cells refined ×4')
    await expect(panel.locator('[data-status]')).toContainText('Field refinement:')
    await panel.locator('[data-frame]').click()
    await panel.locator('[data-mode]').selectOption('xz')
    await panel.locator('[data-slice]').fill('0.5')
    expect(await page.evaluate(() => window.__nadocTest.scene.getObjectByName('experimental-em-field')?.userData.sampleCount)).toBeGreaterThan(100)
    const legend=page.locator('#em-scale')
    await expect(legend).toBeVisible()
    await expect(page.locator('.sidebar-column[data-panel-type="em"]')).toBeVisible()
    await panel.locator('[data-mode]').selectOption('smooth')
    await page.waitForFunction(()=>window.__nadocTest.scene.getObjectByName('experimental-em-field')?.children.some(o=>o.userData.emSmooth))
    if(process.env.NADOC_EM_LAYER_REVIEW)await page.screenshot({path:process.env.NADOC_EM_LAYER_REVIEW})
    const originalGeometry=await page.evaluate(()=>window.__nadocTest.scene.getObjectByName('experimental-em-field').children.find(o=>o.isMesh).geometry.uuid)
    await page.locator('#em-scale-cmap').click()
    await page.locator('#em-scale-cmap-popup [data-cmap="magma"]').click()
    expect(await page.evaluate(()=>window.__nadocTest.scene.getObjectByName('experimental-em-field').children.find(o=>o.isMesh).geometry.uuid)).toBe(originalGeometry)
    await panel.locator('[data-mode]').selectOption('volume')
    await page.locator('#em-scale-max').fill('150')
    await page.locator('#em-scale-max').press('Tab')
    await page.locator('#right-tab-toggle').click()
    await expect(page.locator('#right-panel')).toHaveClass(/hidden/)
    expect((await page.locator('#right-panel').boundingBox()).width).toBe(0)
    await expect(legend).toBeVisible()
    await page.locator('#right-tab-toggle').click()
    await expect(panel).toBeVisible()
    await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click()
    await expect(panel).not.toBeVisible();await expect(legend).toBeVisible()
    expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('nadoc.em.colors.v1')))).toMatchObject({maximum:150,colormap:'magma'})
    await page.locator('.right-tab-btn[data-tab="em"]').click()
    await expect(panel).toBeVisible();await expect(page.locator('#em-scale-max')).toHaveValue('150.00')
    await panel.locator('[data-mode]').selectOption('volume')
    await panel.locator('[data-clear]').click()
    await expect(legend).not.toBeVisible()
    await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click()
    // Rail clicks add columns; free space before opening Simulations.
    for (const side of ['left','right']) {
      const close = page.locator(`#${side}-panel .sidebar-close:visible`)
      while (await close.count()) await close.first().click()
    }
    await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
    await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
    const ox = page.locator('#oxdna-jobs-viz-body')
    if (!await ox.isVisible()) await page.locator('#oxdna-jobs-viz-toggle').click()
    await ox.locator('[data-em-settings]').click()
    await expect(panel.locator('[data-shell]')).toHaveValue('none')
    await expect(panel.locator('[data-dot-size]')).toHaveValue('6')
    await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click()
    await ox.locator('[data-em-toggle]').check()
    await expect(ox.locator('[data-em-status]')).toContainText('Select a simulation visualization')
    await ox.locator('[data-em-toggle]').uncheck()
    await page.locator('.engine-selector-btn[data-engine="namd"]').click()
    const md = page.locator('#md-jobs-viz-body')
    if (!await md.isVisible()) await page.locator('#md-jobs-viz-toggle').click()
    await md.locator('[data-em-settings]').click()
    await expect(panel.locator('[data-dot-size]')).toHaveValue('6')
    await page.locator('.sidebar-column[data-panel-type="em"] .sidebar-close').click()
    expect(errors).toEqual([])
  } finally {
    if (errors.length) console.log('EM_BROWSER_ERRORS', errors)
    expect(await digest()).toBe(before)
  }
})
