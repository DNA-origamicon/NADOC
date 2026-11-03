import { expect, test } from '@playwright/test'
import { readFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'

test.setTimeout(90_000)
for (const [context, stereo, keys] of [
  ['same strand', 'cis-anti-I', ['h0:2:FORWARD', 'h0:3:FORWARD']],
  ['different strands', 'trans-syn-II', ['h0:2:FORWARD', 'h0:3:REVERSE']],
  ['extra bases', 'trans-syn-I', ['__xb__:xo_direct:0', '__xb__:xo_direct:1']],
]) {
  test(`contextual CPD conversion: ${context}`, async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 1000 })
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
    await page.goto(`/?doc=__e2e__cpd_context_${stereo}`)
    await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
    await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
    await page.locator('#menu-file-new').click()
    await page.fill('#new-design-name', `__e2e__cpd_context_${stereo}`)
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    const design = JSON.parse(readFileSync(path.resolve('../tests/fixtures', context === 'extra bases' ? 'cpd_extra_pair.nadoc' : 'cpd_conversion_context.nadoc'), 'utf8'))
    design.metadata.name = `__e2e__cpd_context_${stereo}`
    await page.evaluate(async ({ content, keys, extra }) => {
      await window.__nadocTest.nanoparticles.importDesign(content)
      await window.__nadocTest.setRepresentation('full')
      const { store } = await import('/src/state/store.js')
      const items = extra ? [{ kind: 'crossover', id: 'xo_direct', subtype: 'crossover' }] : keys.map(key => ({ kind: 'base', key }))
      store.setState({ selection: { items, primary: items[0] } })
    }, { content: JSON.stringify(design), keys, extra: context === 'extra bases' })
    const before = await page.evaluate(() => window.__nadocTest.getDesignRenderer().getHelixCtrl().getSlabFrames())
    await page.locator('#canvas').click({ button: 'right', position: { x: 300, y: 200 } })
    await page.getByText('Convert to CPD…', { exact: true }).click()
    const button = page.getByRole('button', { name: 'Convert to CPD', exact: true })
    await expect(button).toBeEnabled()
    await expect(page.getByLabel('CPD type').locator('option')).toHaveCount(4)
    const previewResponse = page.waitForResponse(r => r.url().includes('/conversion-preview') && r.request().postDataJSON()?.stereochemistry === stereo)
    await page.getByLabel('CPD type').selectOption(stereo)
    const preview = await (await previewResponse).json()
    expect(preview.relationship).toBe(context === 'different strands' ? 'different strands' : 'same strand')
    await expect(button).toBeEnabled()
    await expect(page.getByLabel('3D CPD selection preview')).toBeVisible()
    const productPixels = await page.getByLabel('3D CPD selection preview').screenshot()
    await page.getByLabel('Show original thymines').check()
    const originalPixels = await page.getByLabel('3D CPD selection preview').screenshot()
    expect(productPixels.equals(originalPixels)).toBe(false)
    await page.getByLabel('Show original thymines').uncheck()
    const reviewDir = path.resolve('../.development-artifacts/cpd-conversion-review')
    mkdirSync(reviewDir, { recursive: true })
    await page.screenshot({ path: path.join(reviewDir, `${stereo}-preview.png`) })
    const conversionResponse = page.waitForResponse(r => r.url().endsWith('/photoproducts/convert'))
    await button.click()
    if ((await conversionResponse).status() === 409) {
      // A delayed document metadata save can advance the revision during the
      // screenshot. Exercise the explicit refresh flow; never bypass its guard.
      await expect(page.getByRole('dialog').getByRole('status')).toContainText('Refresh the preview')
      await page.getByRole('button', { name: 'Refresh preview', exact: true }).click()
      await expect(button).toBeEnabled()
      await button.click()
    }
    await expect(button).not.toBeVisible()
    // Observe the converted pair at a useful scale, using the same actual
    // molecular coordinates as the preview. This changes only the camera.
    await page.evaluate(preview => {
      const selected = preview.positions.filter((_, i) => preview.selected[i])
      const center = selected.reduce((a, p) => a.map((v, i) => v + p[i] / selected.length), [0, 0, 0])
      window.__nadocTest.applyCameraPoseForTest({ target: center, position: center.map((v, i) => v + [2, 1, 4][i]) })
    }, preview)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.getObjectByName('cpdSlabBonds')?.count)).toBe(2)
    const after = await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      return { frames: window.__nadocTest.getDesignRenderer().getHelixCtrl().getSlabFrames(), lesion: store.getState().currentDesign.photoproduct_junctions[0] }
    })
    expect(after.lesion.stereochemistry).toBe(stereo)
    expect(after.lesion.bond_relaxation.backbone_fixed).toBe(true)
    if (context !== 'extra bases') {
      const changed = after.frames.filter((a, i) => JSON.stringify(a.center) !== JSON.stringify(before[i].center))
      expect(changed.map(a => a.base_key).sort()).toEqual([...keys].sort())
    }
    await page.screenshot({ path: path.join(reviewDir, `${stereo}-full.png`) })
    await page.evaluate(async () => window.__nadocTest.setRepresentation('ballstick'))
    await expect.poll(() => page.evaluate(async key => {
      const { parseBaseKey } = await import('/src/scene/base_ref.js')
      return !!window.__nadocTest.getAtomisticRenderer().residueInfo(parseBaseKey(key))
    }, keys[0])).toBe(true)
    await page.screenshot({ path: path.join(reviewDir, `${stereo}-atoms.png`) })
    // Removal must restore ordinary slabs too, rather than leaving the authored
    // positions cached after deleting the lesion annotation.
    await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const { deletePhotoproduct } = await import('/src/api/client.js')
      await deletePhotoproduct(store.getState().currentDesign.photoproduct_junctions[0].id)
      await window.__nadocTest.setRepresentation('full')
    })
    const restored = await page.evaluate(() => window.__nadocTest.getDesignRenderer().getHelixCtrl().getSlabFrames())
    expect(restored).toEqual(before)
    expect(errors).toEqual([])
  })
}
