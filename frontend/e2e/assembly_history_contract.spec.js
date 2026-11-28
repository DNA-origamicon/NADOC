import { test, expect } from '@playwright/test'

// Isolated launcher owns workspace/autosaves, project stores, browser profiles,
// Vite cache and Playwright outputs. Its finally block stops owned servers and
// removes the entire fresh root on success/failure; no downloads or screenshots.
test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated history launcher')

test('assembly recorded gear edits render and undo as one complete operation', async ({ page, request }) => {
  page.setDefaultTimeout(10000)
  const doc = '__e2e__history-assembly-contract'
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto(`/?doc=${doc}`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => !!window.__nadocTest)
    page.once('dialog', dialog => dialog.accept(doc))
    await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
    await page.locator('#menu-file-new-assembly').click()
    await page.mouse.click(900, 450)
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
    await page.waitForFunction(async () => (await import('/src/state/store.js')).store.getState().assemblyActive)
    const proofHeaders = { 'X-NADOC-Doc': doc }
    const proofStart = await request.post('http://127.0.0.1:8004/api/assembly/features/verification/jobs', { headers: proofHeaders })
    expect(proofStart.status()).toBe(202)
    const proofJob = (await proofStart.json()).job_id
    const proofUrl = `http://127.0.0.1:8004/api/assembly/features/verification/jobs/${proofJob}`
    await expect.poll(async () => (await (await request.get(proofUrl, { headers: proofHeaders })).json()).status,
      { timeout: 30000 }).toBe('complete')
    const proof = await (await request.get(proofUrl, { headers: proofHeaders })).json()
    expect(proof.stale).toBe(false)
    expect(proof.result.status).toBe('verified')
    expect((await (await request.delete(proofUrl, { headers: proofHeaders })).json()).result.status).toBe('unverified')
    await page.evaluate(async name => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const check = value => { if (!value) throw new Error(JSON.stringify(store.getState().lastError)); return value }
      const created = store.getState().currentAssembly
      if (created.recipe_root?.kind !== 'empty' || created.recipe_root?.initial_name !== created.metadata.name) {
        throw new Error('New assembly creation inputs were not preserved')
      }
      for (const suffix of ['A', 'B']) {
        check(await api.addInstance({ name: `${name}-${suffix}`, source: { type: 'inline', design: { id: '__e2e__shared-document-id', metadata: { name: `${name}-${suffix}` }, recipe_root: { kind: 'empty', initial_name: `${name}-${suffix}`, lattice_type: 'HONEYCOMB', version: 1 } } } }))
      }
      const parts = store.getState().currentAssembly.instances
      if (parts[0].source.design.metadata.name === parts[1].source.design.metadata.name) {
        throw new Error('Distinct revisions of the same source document collapsed')
      }
      check(await api.addAssemblyJoint({ instance_b_id: parts[0].id, current_value: 0.4 }))
      check(await api.addAssemblyJoint({ instance_b_id: parts[1].id }))
      const joints = store.getState().currentAssembly.joints
      check(await api.createGearRelation({ joint_a_id: joints[0].id, joint_b_id: joints[1].id,
        ratio: 2, invert: true, capture_anchors_from_current: false }))
      const relation = store.getState().currentAssembly.gear_relations[0].id
      check(await api.patchGearRelation(relation, { ratio: 3 }))
      check(await api.resolveGearRelation(relation))
    }, doc)
    const target = page.getByTitle('Select assembly or part feature log')
    await target.selectOption('__assembly__')
    await expect(page.locator('#fl-list')).toContainText('Update gear relation')
    await expect(page.locator('#fl-list')).toContainText('Resolve gear relation')
    await expect(page.locator('#fl-list')).toContainText('Gear 3')
    const read = () => page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const assembly = store.getState().currentAssembly
      return { angle: assembly.joints[1].current_value, ratio: assembly.gear_relations[0].ratio,
        features: assembly.feature_log.map(row => row.id) }
    })
    const before = await read()
    if (Math.abs(before.angle + 1.2) > 0.001) console.log('Assembly history mismatch', await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const result = await api.getAssembly()
      const value = store.getState().currentAssembly
      return { response: !!result, gears: value.gear_relations, joints: value.joints.map(j => ({ id: j.id, value: j.current_value })),
        commands: value.feature_log.map(row => ({ kind: row.op_kind, inputs: row.params.inputs })) }
    }))
    expect(before.angle).toBeCloseTo(-1.2)
    await page.getByTitle('Edit F6', { exact: true }).click()
    const editDialog = page.getByRole('dialog').filter({ hasText: 'Edit F6' })
    await expect(editDialog.getByRole('spinbutton', { name: 'Ratio', exact: true })).toHaveValue('3')
    await editDialog.getByRole('spinbutton', { name: 'Ratio', exact: true }).fill('4')
    await editDialog.getByRole('button', { name: 'Save', exact: true }).click()
    const applyEdit = page.getByRole('dialog', { name: 'Apply edit F6', exact: true })
    await applyEdit.getByRole('button', { name: 'Apply edit', exact: true }).click()
    await expect(applyEdit).not.toBeVisible({ timeout: 30000 })
    await expect.poll(async () => (await read()).angle).toBeCloseTo(-1.6)
    expect((await read()).features).toEqual(before.features)
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(read).toEqual(before)
    await page.evaluate(async () => (await import('/src/api/client.js')).redoAssembly())
    await expect.poll(async () => (await read()).ratio).toBe(4)
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const first = store.getState().currentAssembly.instances[0].id
      if (!await api.createGroup({ instanceIds: [first], name: '__e2e__moving' })) throw new Error('Group failed')
      const group = store.getState().currentAssembly.groups[0].id
      if (!await api.transformGroup(group, { translation: [2, 0, 0] })) throw new Error('Move failed')
      const index = store.getState().currentAssembly.feature_log.length - 1
      if (!await api.editAssemblyFeature(index, { translation: [3, 0, 0] })) throw new Error('Move edit failed')
    })
    await expect(page.locator('#fl-list')).toContainText('Move group')
    const groupHistory = await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const value = store.getState().currentAssembly
      return value.feature_log.at(-1).params.inputs.translation
    })
    expect(groupHistory).toEqual([3, 0, 0])
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    expect(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState()
      .currentAssembly.feature_log.at(-1).params.inputs.translation)).toEqual([2, 0, 0])
    const jointBefore = await read()
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const id = store.getState().currentAssembly.joints[0].id
      if (!await api.patchAssemblyJoint(id, { current_value: 0.5, max_limit: 1 })) throw new Error('Joint update failed')
      const index = store.getState().currentAssembly.feature_log.length - 1
      if (!await api.editAssemblyFeature(index, { current_value: 0.6 })) throw new Error('Joint history edit failed')
    })
    await expect(page.locator('#fl-list')).toContainText('Update joint')
    await expect.poll(async () => (await read()).angle).toBeCloseTo(-2.4)
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(async () => (await read()).angle).toBeCloseTo(-2)
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(read).toEqual(jointBefore)
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const joints = store.getState().currentAssembly.joints
      if (!await api.createBeltPath({ name: '__e2e__belt',
        pulley_a: { joint_id: joints[0].id, radius: 2, center_world: [0, 0, 0] },
        pulley_b: { joint_id: joints[1].id, radius: 2, center_world: [10, 0, 0] },
      })) throw new Error('Belt creation failed')
      const belt = store.getState().currentAssembly.belt_paths[0].id
      if (!await api.patchBeltPath(belt, { name: '__e2e__patched-belt' })) throw new Error('Belt patch failed')
      const index = store.getState().currentAssembly.feature_log.length - 1
      if (!await api.editAssemblyFeature(index, { name: '__e2e__edited-belt' })) throw new Error('Belt history edit failed')
    })
    await expect(page.locator('#fl-list')).toContainText('Update belt path')
    const beltName = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState()
      .currentAssembly.belt_paths[0].name)
    await expect.poll(beltName).toBe('__e2e__edited-belt')
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(beltName).toBe('__e2e__patched-belt')
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(beltName).toBe('__e2e__belt')
    const sourceBefore = await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      return store.getState().currentAssembly.instances.map(i => i.source.design.metadata.name)
    })
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const instance = store.getState().currentAssembly.instances[0]
      const design = structuredClone(instance.source.design)
      design.metadata.name = '__e2e__edited-source'
      if (!await api.patchInstanceDesign(instance.id, JSON.stringify(design))) throw new Error('Source revision update failed')
    })
    await expect(page.locator('#fl-list')).toContainText('Source Revision')
    const sourceNames = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState()
      .currentAssembly.instances.map(i => i.source.design.metadata.name))
    await expect.poll(sourceNames).toEqual(['__e2e__edited-source', sourceBefore[1]])
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(sourceNames).toEqual(sourceBefore)
    const instanceName = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState()
      .currentAssembly.instances[0].name)
    const originalName = await instanceName()
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const id = store.getState().currentAssembly.instances[0].id
      if (!await api.patchInstance(id, { name: '__e2e__configured', allow_part_joints: true })) throw new Error('Instance property update failed')
      const index = store.getState().currentAssembly.feature_log.length - 1
      if (!await api.editAssemblyFeature(index, { name: '__e2e__edited-instance' })) throw new Error('Instance history edit failed')
    })
    await expect(page.locator('#fl-list')).toContainText('Update part instance')
    await expect.poll(instanceName).toBe('__e2e__edited-instance')
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(instanceName).toBe('__e2e__configured')
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(instanceName).toBe(originalName)
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      if (!await api.patchInstance(store.getState().currentAssembly.instances[0].id, { name: '__e2e__evaluation' })) throw new Error('Evaluation seed failed')
    })
    const featureCount = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentAssembly.feature_log.length)
    const evaluatedRow = page.locator(`#fl-list [data-fl-row="${featureCount}"]`)
    await evaluatedRow.click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'View dependencies', exact: true }).click()
    const dependenciesDialog = page.getByRole('dialog', { name: `F${featureCount} dependencies`, exact: true })
    await expect(dependenciesDialog).toBeVisible()
    await expect(dependenciesDialog.getByLabel('Parents', { exact: true })).toContainText('F1: Part')
    await expect(dependenciesDialog.getByLabel('Dependents', { exact: true })).toContainText('None')
    await expect(dependenciesDialog).toContainText('conservative ordering dependencies')
    await dependenciesDialog.getByRole('button', { name: 'Close', exact: true }).last().click()
    await evaluatedRow.click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Suppress', exact: true }).click()
    const suppressDialog = page.getByRole('dialog', { name: `Suppress F${featureCount}`, exact: true })
    await expect(suppressDialog).toBeVisible()
    await suppressDialog.getByRole('button', { name: 'Suppress', exact: true }).click()
    await expect(suppressDialog).not.toBeVisible({ timeout: 30000 })
    await expect.poll(instanceName).toBe(originalName)
    await expect(evaluatedRow).toContainText('Suppressed')
    await evaluatedRow.click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Unsuppress', exact: true }).click()
    const unsuppressDialog = page.getByRole('dialog', { name: `Unsuppress F${featureCount}`, exact: true })
    await unsuppressDialog.getByRole('button', { name: 'Unsuppress', exact: true }).click()
    await expect(unsuppressDialog).not.toBeVisible({ timeout: 30000 })
    await expect.poll(instanceName).toBe('__e2e__evaluation')
    await expect(evaluatedRow).not.toContainText('Suppressed')
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(instanceName).toBe(originalName)
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(instanceName).toBe('__e2e__evaluation')
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(instanceName).toBe(originalName)
    const moveSource = await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      const parts = store.getState().currentAssembly.instances
      await api.patchInstance(parts[0].id, { name: '__e2e__move-first' })
      await api.patchInstance(parts[1].id, { name: '__e2e__move-second' })
      return store.getState().currentAssembly.feature_log.map(row => row.id)
    })
    await page.locator(`#fl-list [data-fl-row="${moveSource.length - 1}"]`).click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Move…', exact: true }).click()
    const moveDialog = page.getByRole('dialog', { name: `Move F${moveSource.length - 1}`, exact: true })
    await moveDialog.getByLabel('New feature position').selectOption(String(moveSource.length - 1))
    await moveDialog.getByRole('button', { name: 'Move', exact: true }).click()
    await expect(moveDialog).not.toBeVisible({ timeout: 30000 })
    expect(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState()
      .currentAssembly.feature_log.at(-1).id)).toBe(moveSource.at(-2))
    for (let step = 0; step < 3; step++) await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(instanceName).toBe(originalName)
    const beforeDeletion = await page.evaluate(async () => structuredClone(
      (await import('/src/state/store.js')).store.getState().currentAssembly))
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      if (!await api.deleteInstance(store.getState().currentAssembly.instances[0].id)) throw new Error('Delete failed')
    })
    await expect(page.locator('#fl-list')).toContainText('Delete part')
    await expect.poll(async () => page.evaluate(async () => {
      const a = (await import('/src/state/store.js')).store.getState().currentAssembly
      return [a.instances.length, a.gear_relations.length, a.belt_paths.length]
    })).toEqual([1, 0, 0])
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(async () => page.evaluate(async () =>
      (await import('/src/state/store.js')).store.getState().currentAssembly)).toEqual(beforeDeletion)
    expect(errors).toEqual([])
  } finally {
    await page.close()
    await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`, { timeout: 5000 }).catch(() => {})
  }
})

test('assembly input editors exclude source definitions', async ({ page, request }) => {
  const doc = '__e2e__history-source-ownership'
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
    const api = await import('/src/api/client.js')
    if (!await api.addInstance({ name: 'Source instance', source: { type: 'inline', design } })) throw new Error('Add failed')
  }, source)
  const readSource = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState()
    .currentAssembly.instances[0].source.design)
  const admittedSource = await readSource()
  await page.getByTitle('Select assembly or part feature log').selectOption('__assembly__')
  await page.getByTitle('Edit F1', { exact: true }).click()
  const edit = page.getByRole('dialog').filter({ hasText: 'Edit F1' })
  await expect(edit.getByLabel('Name', { exact: true })).toBeVisible()
  await expect(edit.getByLabel('Source', { exact: true })).toHaveCount(0)
  await expect(edit.getByLabel('Length bp', { exact: true })).toHaveCount(0)
  await edit.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(await readSource()).toEqual(admittedSource)
})

test('assembly suppression from F0 rebuilds the tail and undo restores F0', async ({ page, request }) => {
  const doc = '__e2e__history-prefix-suppression'
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto(`/?doc=${doc}`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => !!window.__nadocTest)
    page.once('dialog', dialog => dialog.accept(doc))
    await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
    await page.locator('#menu-file-new-assembly').click()
    await page.mouse.click(900, 450)
    await page.waitForFunction(async () => (await import('/src/state/store.js')).store.getState().assemblyActive)
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      const { store } = await import('/src/state/store.js')
      if (!await api.addInstance({ name: 'Original', source: { type: 'inline', design: {
        id: '__e2e__prefix-part', metadata: { name: 'Prefix part' }, recipe_root: {
          version: 1, kind: 'empty', initial_name: 'Prefix part', lattice_type: 'HONEYCOMB',
        },
      } } })) throw new Error('Add failed')
      if (!await api.patchInstance(store.getState().currentAssembly.instances[0].id, { name: 'Renamed' })) throw new Error('Patch failed')
    })
    await page.getByTitle('Select assembly or part feature log').selectOption('__assembly__')
    await page.evaluate(async () => (await import('/src/api/client.js')).seekAssemblyFeatures(-2))
    const read = () => page.evaluate(async () => {
      const a = (await import('/src/state/store.js')).store.getState().currentAssembly
      return { cursor: a.feature_log_cursor, names: a.instances.map(i => i.name), suppressed: a.feature_log[1].suppressed }
    })
    await expect.poll(read).toEqual({ cursor: -2, names: [], suppressed: false })
    await page.locator('#fl-list [data-fl-row="2"]').click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Suppress', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Suppress F2', exact: true })
    await dialog.getByRole('button', { name: 'Suppress', exact: true }).click()
    await expect(dialog).not.toBeVisible({ timeout: 30000 })
    await expect.poll(read).toEqual({ cursor: -1, names: ['Original'], suppressed: true })
    await page.evaluate(async () => (await import('/src/api/client.js')).undoAssembly())
    await expect.poll(read).toEqual({ cursor: -2, names: [], suppressed: false })
    await page.evaluate(async () => (await import('/src/api/client.js')).redoAssembly())
    await expect.poll(read).toEqual({ cursor: -1, names: ['Original'], suppressed: true })
    expect(errors).toEqual([])
  } finally {
    await page.close()
    await request.delete(`http://127.0.0.1:8004/api/documents/${doc}`, { timeout: 5000 }).catch(() => {})
  }
})
