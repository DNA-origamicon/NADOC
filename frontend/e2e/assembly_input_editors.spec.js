import { test, expect } from '@playwright/test'

// The isolated history launcher owns workspace/autosaves, project stores,
// browser profiles, caches and Playwright outputs; its finally removes the root.
// No files outside that root, downloads, screenshots, traces or videos.
test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')

test('assembly input editors preserve source parts and regenerate typed edits', async ({ page, request }) => {
  const doc = '__e2e__history-input-editors'
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`/?doc=${doc}`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => !!window.__nadocTest)
  const response = await request.post('http://127.0.0.1:8004/api/design/bundle', {
    headers: { 'X-NADOC-Doc': `${doc}-source` }, data: { cells: [[0, 0]], length_bp: 21 },
  })
  expect(response.ok()).toBe(true)
  const source = (await response.json()).design
  page.once('dialog', dialog => dialog.accept(doc))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new-assembly').click()
  await page.mouse.click(900, 450)
  await page.waitForFunction(async () => (await import('/src/state/store.js')).store.getState().assemblyActive)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js'), { store } = await import('/src/state/store.js')
    const check = value => { if (!value) throw new Error(JSON.stringify(store.getState().lastError)) }
    check(await api.addInstance({ name: 'Source instance', source: { type: 'inline', design } }))
    const assembly = store.getState().currentAssembly
    const id = assembly.instances[0].id
    await api.refreshAssemblyPatternContext(assembly)
    check(await api.createAssemblyPattern('linear-pattern', { instance_ids: [id], parameters: { instances: 3, spacing: 8, direction: 'X' },
      expected_assembly_id: assembly.id, expected_revision: api.assemblyPatternRevision(), expected_feature_ids: assembly.feature_log.map(row => row.id) }))
    const copy = store.getState().currentAssembly.instances[2].id
    check(await api.addAssemblyJoint({ instance_b_id: id, min_limit: -1, max_limit: 2 }))
    const joint = store.getState().currentAssembly.joints[0].id
    check(await api.patchAssemblyJoint(joint, { current_value: 0.1 }))
    check(await api.patchInstance(copy, { name: 'Dependent copy' }))
  }, source)
  await page.getByTitle('Select assembly or part feature log').selectOption('__assembly__')
  const read = () => page.evaluate(async () => {
    const a = (await import('/src/state/store.js')).store.getState().currentAssembly
    return { count: a.instances.length, min: a.joints[0]?.min_limit, max: a.joints[0]?.max_limit,
      names: a.instances.map(i => i.name), positions: a.instances.map(i => i.transform.values[3]),
      features: a.feature_log.map(row => row.id), sources: a.instances.map(i => JSON.stringify(i.source.design)) }
  })
  async function open(index) {
    await page.getByTitle(`Edit F${index}`, { exact: true }).click()
    return page.getByRole('dialog').filter({ hasText: `Edit F${index}` })
  }
  async function save(dialog, index) {
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    const apply = page.getByRole('dialog', { name: `Apply edit F${index}`, exact: true })
    await apply.getByRole('button', { name: 'Apply edit', exact: true }).click()
    return apply
  }
  const before = await read()
  const joint = await open(4)
  await joint.getByLabel('Min limit action', { exact: true }).selectOption('null')
  await expect(await save(joint, 4)).not.toBeVisible({ timeout: 30000 })
  await expect.poll(async () => (await read()).min).toBeNull()
  expect((await read()).max).toBe(2)
  await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
  await expect.poll(read).toEqual(before)
  const pattern = await open(2)
  await pattern.getByRole('spinbutton', { name: 'Parameters / Spacing', exact: true }).fill('12')
  await expect(await save(pattern, 2)).not.toBeVisible({ timeout: 30000 })
  await expect.poll(async () => (await read()).positions).toEqual([0, 12, 24])
  expect((await read()).names[2]).toBe('Dependent copy')
  expect((await read()).features).toEqual(before.features)
  expect((await read()).sources).toEqual(before.sources)
  const changed = await read()
  const invalid = await open(2)
  await invalid.getByRole('spinbutton', { name: 'Parameters / Instances', exact: true }).fill('2')
  const refusal = await save(invalid, 2)
  await expect(refusal.getByRole('status')).not.toHaveText('Checking dependencies and regenerating…', { timeout: 30000 })
  await expect(refusal).toBeVisible()
  expect(await read()).toEqual(changed)
  await refusal.getByRole('button', { name: 'Cancel', exact: true }).click()
  const cancelled = await open(2)
  await cancelled.getByRole('spinbutton', { name: 'Parameters / Spacing', exact: true }).fill('100')
  await cancelled.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(await read()).toEqual(changed)
  await page.evaluate(async () => { const api = await import('/src/api/client.js'); await api.importAssembly(await api.getAssemblyContent()) })
  expect(await read()).toEqual(changed)
  const proof = await request.post('http://127.0.0.1:8004/api/assembly/features/verification/jobs', { headers: { 'X-NADOC-Doc': doc } })
  expect(proof.status()).toBe(202)
  const url = `http://127.0.0.1:8004/api/assembly/features/verification/jobs/${(await proof.json()).job_id}`
  await expect.poll(async () => (await (await request.get(url, { headers: { 'X-NADOC-Doc': doc } })).json()).status).toBe('complete')
  expect((await (await request.get(url, { headers: { 'X-NADOC-Doc': doc } })).json()).result.status).toBe('verified')
  expect(errors).toEqual([])
})
