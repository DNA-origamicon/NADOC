import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

test('VR fixed levels accumulate terminal bases and clear only on an empty trigger click', async ({ page }) => {
  test.setTimeout(90000)
  const feedback = []
  await page.route('**/api/vr/feedback', async route => {
    feedback.push(route.request().postDataJSON())
    await route.fulfill({ json: { ok: true } })
  })
  await loadScaffoldedPart(page, { doc: 'vr-selection-accumulation', extraQuery: '&scrywrite=1' })
  const identities = await page.evaluate(() => {
    const geometry = window.__nadocTest.store.getState().currentGeometry
    const identity = n => ['nuc', n.strand_id || '_', n.domain_index || 0,
      n.helix_id || '_', n.bp_index || 0, n.direction || '_', n.copy_k || n.ext_k || 0, 'slab'].join(':')
    return {
      ends: geometry.filter(n => n.is_five_prime || n.is_three_prime).map(identity),
      bases: geometry.slice(0, 20).map(identity),
      interior: identity(geometry.find(n => !n.is_five_prime && !n.is_three_prime)),
    }
  })
  expect(identities.ends.length).toBeGreaterThanOrEqual(2)
  let sequence = 0
  const select = async identities => {
    await page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event),
      { type: 'select', sequence: ++sequence, identities })
    await expect.poll(() => feedback.length).toBe(sequence)
    return page.evaluate(() => window.__nadocTest.getCanonicalSelection())
  }
  const level = level => page.evaluate(level => window.__nadocTest.scrywrite.dispatch({ type: 'selection_level', level }), level)
  for (const mode of ['base', 'end']) {
    await level(mode)
    await select([])
    const first = await select([identities.ends[0]])
    const both = await select([identities.ends[1]])
    expect(both.items).toHaveLength(2)
    expect(both.items).toContainEqual(first.primary)
    expect(both.items.every(ref => ref.kind === mode)).toBe(true)
    expect(feedback.at(-1).selected_owner_tokens).toHaveLength(2)
    expect(await page.evaluate(() => window.__nadocTest.scene
      .getObjectByName('endExtrudeArrows').children.filter(child => child.userData.dragMeta).length)).toBe(2)
    const repeated = await select([identities.ends[0]])
    expect(repeated.items).toHaveLength(2)
    expect(repeated.primary).toEqual(first.primary)
    expect((await select(identities.ends.slice(0, 2))).items).toHaveLength(2)
    if (mode === 'end') expect((await select([identities.interior])).items).toHaveLength(2)
    expect((await select([])).items).toEqual([])
    expect(feedback.at(-1).selected_owner_tokens).toEqual([])
  }
  await level('base')
  await select(identities.bases.slice(0, 16))
  expect((await select(identities.bases.slice(16))).items).toHaveLength(20)
  expect(feedback.at(-1).selected_owner_tokens).toHaveLength(20)
  await select([])
  for (const mode of ['strand', 'domain', 'cluster']) {
    await level(mode)
    const first = await select([identities.ends[0]])
    expect(first.items).toHaveLength(1)
    expect((await select([identities.ends[0]])).items).toEqual(first.items)
    await select([])
  }
  await level('base')
  const baseSelection = await select([identities.ends[0]])
  await level('strand')
  const mixed = await select([identities.ends[1]])
  expect(mixed.items).toHaveLength(2)
  expect(mixed.items).toContainEqual(baseSelection.primary)
  expect(mixed.primary.kind).toBe('strand')
  expect((await select(['unknown:primitive'])).items).toEqual(mixed.items)
  await select([])
  await level('default')
  expect((await select([identities.ends[0]])).primary.kind).toBe('strand')
  const drilled = await select([identities.ends[0]])
  expect(drilled.primary.kind).toBe('base')
  expect(drilled.items).toHaveLength(1)
  expect((await select([])).items).toEqual([])
})
