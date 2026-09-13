import { test, expect } from '@playwright/test'
import { readdirSync, rmSync, existsSync, rmdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Persisted artifacts: only workspace/namd_surfaces/__e2e__namd-peg-direct*.json.
// afterAll and global teardown both remove them, including after failed tests.
// No design fixture; the throwaway backend disables session-cache writes.
// Screenshots live in Playwright's output directory and its cleanup reporter removes them.
const directory = fileURLToPath(new URL('../../workspace/namd_surfaces/', import.meta.url))
const prefix = '__e2e__namd-peg-direct'
const existed = existsSync(directory)
test.beforeAll(() => {
  const existing = existsSync(directory) ? readdirSync(directory).filter(name => name.startsWith(prefix)) : []
  expect(existing, 'scratch surface names must be unused before the test').toEqual([])
})
test.afterAll(() => {
  if (!existsSync(directory)) return
  for (const name of readdirSync(directory).filter(name => name.startsWith(prefix))) rmSync(`${directory}/${name}`, { force: true })
  if (!existed && !readdirSync(directory).length) rmdirSync(directory)
})

async function openNative(page) {
  await page.route(/\/api\/(md|oxdna|mrdna|lammps|blade|snupi|cando)\/jobs(?:\?.*)?$/, route =>
    route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.fallback())
  await page.goto('/?doc=__e2e__namd-peg-direct')
  await page.locator('#menu-bar .menu-item > button', { hasText: /^File$/ }).click()
  await page.locator('#menu-namd-peg-surfaces').click()
  await expect(page.getByRole('dialog', { name: 'NAMD PEG surface setup' })).toBeVisible()
}

test('create and reopen a direct NAMD PEG surface without oxDNA or DNA', async ({ page }, info) => {
  test.setTimeout(60000)
  const errors = [], launches = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route(/\/api\/(md|oxdna)\/jobs(?:\/[^/]+\/start)?(?:\?.*)?$/, route => {
    if (route.request().method() === 'POST') { launches.push(route.request().url()); return route.abort() }
    return route.continue()
  })
  await openNative(page)
  const dialog = page.getByRole('dialog', { name: 'NAMD PEG surface setup' })
  await dialog.getByLabel('Surface name', { exact: true }).fill(prefix)
  await dialog.getByRole('combobox', { name: 'Support', exact: true }).selectOption('graphene')
  await dialog.getByRole('combobox', { name: 'Allowed-side normal', exact: true }).selectOption('-y')
  await dialog.getByLabel('Plane position (nm)').fill('-7')
  await dialog.getByRole('combobox', { name: 'Patch shape', exact: true }).selectOption('circle')
  await dialog.getByLabel('Patch width / diameter (nm)').fill('24')
  await dialog.getByLabel('Pore diameter (nm; 0 = no pore)').fill('3')
  await dialog.getByLabel('Ethylene-oxide repeat units / chain').fill('45')
  await dialog.getByLabel('Grafted and free end groups').fill('OH / graft linker (to specify)')
  await expect(dialog.locator('.namd-peg-estimate')).toContainText('22 requested chains')
  const style = await dialog.getByLabel('Ethylene-oxide repeat units / chain').evaluate(node => {
    const css = getComputedStyle(node); return { color: css.color, background: css.backgroundColor }
  })
  expect(style).toEqual({ color: 'rgb(201, 209, 217)', background: 'rgb(22, 27, 34)' })
  if (process.env.NADOC_PEG_VISUAL_REVIEW) await page.screenshot({ path: info.outputPath('surface-form.png') })
  await dialog.getByRole('button', { name: 'Review surface', exact: true }).click()
  await expect(dialog.getByRole('img', { name: 'PEG graft layout preview' })).toBeVisible()
  await expect(dialog).toContainText('22 PEG chains')
  await expect(dialog).toContainText('does not create or start a simulation')
  if (process.env.NADOC_PEG_VISUAL_REVIEW) {
    await page.screenshot({ path: info.outputPath('surface-review.png') })
    await new Promise(resolve => setTimeout(resolve, 15000))
  }
  const savedResponse = page.waitForResponse(r => r.url().endsWith('/api/md/peg-surfaces') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Create surface draft' }).click()
  const saved = await (await savedResponse).json()
  expect(saved.origin).toBe('direct')
  expect(saved.launch_ready).toBe(false)
  expect(saved.spec).toMatchObject({ repeat_units: 45, normal_axis: '-y', position_nm: -7 })
  await expect(dialog).toContainText('Surface draft saved.')
  await dialog.locator('.modal__actions').getByRole('button', { name: 'Close', exact: true }).click()
  await page.reload()
  await page.locator('#menu-bar .menu-item > button', { hasText: /^File$/ }).click()
  await page.locator('#menu-namd-peg-surfaces').click()
  await dialog.getByLabel('Open saved surface').selectOption(saved.id)
  await expect(dialog.getByLabel('Ethylene-oxide repeat units / chain')).toHaveValue('45')
  await dialog.getByLabel('Ethylene-oxide repeat units / chain').fill('50')
  await dialog.getByRole('button', { name: 'Review surface', exact: true }).click()
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click()
  await expect(dialog).toContainText('Surface draft saved.')
  expect(launches).toEqual([])
  expect(errors).toEqual([])
})

test('invalid layout stays editable and reports a specific error', async ({ page }) => {
  await openNative(page)
  const dialog = page.getByRole('dialog', { name: 'NAMD PEG surface setup' })
  await dialog.getByRole('combobox', { name: 'Support', exact: true }).selectOption('graphene')
  await dialog.getByLabel('Pore diameter (nm; 0 = no pore)').fill('20')
  await dialog.getByRole('button', { name: 'Review surface', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText(/smaller|failed/i)
  await expect(dialog.getByLabel('Pore diameter (nm; 0 = no pore)')).toHaveValue('20')
  await expect(dialog.getByRole('button', { name: 'Create surface draft' })).toBeHidden()
})
