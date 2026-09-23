import { test, expect } from '@playwright/test'

// Inventory: __e2e__ autosave only, temporary NADOC_WORKSPACE with global teardown.
// Real main event handler and backend mutation; native feedback transport isolated.
test('painted Confirm creates visible geometry once and Undo removes that edit', async ({ page }, testInfo) => {
  const errors = [], execution = [], preflight = []
  page.on('pageerror', e => errors.push(e.message))
  for (const [route, output] of [['tool-preflight-feedback', preflight], ['tool-execution-feedback', execution]]) {
    await page.route(`**/api/vr/${route}`, async request => {
      output.push(request.request().postDataJSON())
      await request.fulfill({ json: { acknowledged: true, published: true } })
    })
  }
  await page.route('**/api/vr/scene-refresh', route => route.fulfill({ json: { published: true, scene_revision: 1 } }))
  await page.goto('/?doc=__e2e__vr-painted-commit&scrywrite=1')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR painted commit')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  // A transient missing draft must not kill the native polling/event path.
  await page.evaluate(() => window.__nadocTest.scrywrite.dispatch({ type: 'tool_config', sequence: 6, draft: null }))
  await page.evaluate(() => window.__nadocTest.scrywrite.dispatch({ type: 'tool_config', sequence: 7, draft: {
    mode: 'extrude', target_kind: 'none', target_identity: null, target_owner_tokens: [],
    length_bp: 42, direction_sign: 1, strand_filter: 'both', ligate_adjacent: true,
    footprint_state: 'unresolved', extrude_from: 'XY',
    painted_footprint: { lattice_type: 'HONEYCOMB', cells: [[0,0],[0,1]] },
  } }))
  await expect.poll(() => preflight.some(p => p.status === 'ok' && p.tool_config_sequence === 7)).toBe(true)
  const event = { type: 'tool', sequence: 3, configSequence: 7, mode: 'extrude', action: 'confirm',
    targetIdentity: null, targetKind: 'none', targetOwnerTokens: [] }
  await page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event), event)
  await expect.poll(() => execution.some(e => e.status === 'succeeded' && e.tool_sequence === 3)).toBe(true)
  const committed = await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  expect(committed.helices).toHaveLength(2)
  expect(committed.lattice_frames).toHaveLength(1)
  expect(committed.feature_log.filter(f => f.op_kind === 'extrude-frame')).toHaveLength(1)
  await page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event), event)
  expect(await page.evaluate(() => window.__nadocTest.scrywrite.snapshot().featureLog.length)).toBe(committed.feature_log.length)
  await page.locator('#canvas').click({ position: { x: 30, y: 30 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(300)
  await page.screenshot({ path: testInfo.outputPath('painted-commit.png') })
  await page.evaluate(event => window.__nadocTest.scrywrite.dispatch({ ...event, sequence: 4, action: 'undo' }), event)
  await expect.poll(() => execution.some(e => e.status === 'succeeded' && e.tool_sequence === 4)).toBe(true)
  expect(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.helices.length)).toBe(0)
  expect(execution.find(e => e.status === 'succeeded' && e.tool_sequence === 3).feature_log_entry_id)
    .toBe(execution.find(e => e.status === 'succeeded' && e.tool_sequence === 4).feature_log_entry_id)
  expect(errors).toEqual([])
})
