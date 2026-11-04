import { test, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { loadScaffoldedPart } from './helpers/scene_harness.js'
import { cleanupProjectArtifacts } from './project_artifact_cleanup.js'
const projects = []
test.afterAll(async () => cleanupProjectArtifacts('../workspace', projects))
for (const editor of ['3d', 'cadnano']) {
  test(`custom scaffold paste in ${editor}`, async ({ page, context }) => {
    test.setTimeout(90000)
    const doc = `__e2e__custom-scaffold-${editor}`
    await loadScaffoldedPart(page, { doc, name: `custom-scaffold-${editor}` })
    projects.push(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.id))
    console.log('CUSTOM_SCAFFOLD_PROJECT', projects.at(-1))
    if (editor === 'cadnano') {
      await page.goto(`/cadnano-editor.html?doc=${doc}`)
      await page.waitForFunction(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().currentDesign?.strands?.length > 0)
    }
    await page.keyboard.press('5')
    await page.locator('input[name="asc-scaffold"][value="custom"]').check()
    const textarea = page.locator('#asc-custom-seq')
    await expect(textarea).toBeVisible()
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    const assignments = []
    page.on('request', request => { if (request.url().endsWith('/design/assign-scaffold-sequence') && request.method() === 'POST') assignments.push(request) })
    await page.evaluate(() => navigator.clipboard.writeText('ATGCN123'))
    await textarea.focus()
    await page.keyboard.press('Control+V')
    const popup = page.locator('.scaffold-sequence-error')
    await expect(popup).toBeVisible()
    await expect(popup).toContainText('"N"')
    expect(assignments).toHaveLength(0)
    await mkdir('../.development-artifacts/custom-scaffold', { recursive: true })
    await page.screenshot({ animations: 'disabled', path: `../.development-artifacts/custom-scaffold/${editor}-invalid.png` })
    await popup.getByRole('button', { name: 'OK', exact: true }).click()
    await expect(textarea).toHaveValue('ATGCN123')
    await textarea.fill('')
    await page.evaluate(() => navigator.clipboard.writeText('atgc \n'.repeat(50)))
    await textarea.focus()
    await page.keyboard.press('Control+V')
    await expect(page.locator('#asc-custom-char-count')).toHaveText('200 nt')
    await expect(popup).not.toBeVisible()
    const responsePromise = page.waitForResponse(r => r.url().endsWith('/design/assign-scaffold-sequence') && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    const response = await responsePromise
    expect(response.ok()).toBe(true)
    expect(response.request().postDataJSON().custom_sequence).toBe('ATGC'.repeat(50))
    const result = await response.json()
    expect(result.design.strands.find(s => s.strand_type === 'scaffold').sequence).toBe('ATGC'.repeat(50))
  })
}
