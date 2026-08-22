import { expect } from '@playwright/test'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002') + '/api'

// Canonical short honeycomb ring used by the in-app 6HB preset.
const CELLS_6HB = [[0, 0], [0, 1], [1, 0], [2, 1], [0, 2], [1, 2]]

/**
 * Build every prerequisite for the plate/tube round-trip without a committed
 * workspace fixture: short 6HB -> auto crossovers -> auto break -> explicit
 * overlapping colors and groups. Color red is staples 0+1; group-A is 0+2.
 */
export async function createShort6hbPlateFixture(page, doc) {
  const headers = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  const fixtureName = `__e2e__plate-tube-${doc.replace(/[^a-zA-Z0-9_-]+/g, '-')}`
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')

  // Unlock the editor through its real lifecycle before replacing the empty
  // part with the API-built bundle. Merely injecting a backend design leaves the
  // welcome overlay up by design.
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', fixtureName)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 15_000 })
  await expect.poll(async () => (await page.request.get(`${API}/design`, { headers })).status())
    .toBe(200)

  // Run prerequisites through the page's own client. This keeps its store and
  // autosave source aligned with the backend after every operation (a separate
  // APIRequestContext can race a pending empty-design autosave).
  const built = await page.evaluate(async ({ cells, fixtureName }) => {
    const api = await import('/src/api/client.js')
    const created = await api.createBundle({
      cells, lengthBp: 42, name: fixtureName,
      plane: 'XY', latticeType: 'HONEYCOMB',
    })
    const crossed = await api.addAutoCrossover()
    const broken = await api.addAutoBreak()
    // Keep the response itself authoritative even if an unrelated background
    // response made the client's stale-response guard skip a store application.
    if (broken?.design) window.__nadocTest.store.setState({ currentDesign: broken.design })
    const staples = (broken?.design?.strands || [])
      .filter(s => s.strand_type === 'staple' && !s.is_reference)
    return {
      ids: staples.slice(0, 3).map(s => s.id),
      stageCounts: [created, crossed, broken].map(x =>
        (x?.design?.strands || []).filter(s => s.strand_type === 'staple' && !s.is_reference).length),
      lastError: window.__nadocTest.store.getState().lastError,
    }
  }, { cells: CELLS_6HB, fixtureName })
  expect(built.ids.length,
    `short 6HB must provide at least three test staples; stages=${built.stageCounts}; error=${JSON.stringify(built.lastError)}`,
  ).toBe(3)
  const ids = built.ids

  await page.evaluate(async (strandIds) => {
    const api = await import('/src/api/client.js')
    const groups = [
      { id: 'group-A', name: 'Group A', color: null, strandIds: [strandIds[0], strandIds[2]] },
      { id: 'group-B', name: 'Group B', color: null, strandIds: [strandIds[1]] },
    ]
    const store = window.__nadocTest.store
    store.setState({
      strandColors: {
        ...(store.getState().strandColors || {}),
        [strandIds[0]]: 0xf01234,
        [strandIds[1]]: 0xf01234,
        [strandIds[2]]: 0x1267e8,
      },
      strandGroups: groups,
    })
    await api.patchStrandsColor(strandIds.slice(0, 2), '#f01234')
    await api.patchStrandsColor([strandIds[2]], '#1267e8')
    await api.saveStapleGroups(groups)
  }, ids)
  await page.waitForFunction(({ ids }) => {
    const state = window.__nadocTest?.store?.getState?.()
    const current = new Set((state?.currentDesign?.strands || []).map(s => s.id))
    return ids.every(id => current.has(id)) && state?.strandGroups?.some(g => g.id === 'group-A')
  }, { ids }, { timeout: 20_000 })

  return { API, headers, ids }
}

export async function readPlateLayout(page, API, headers) {
  const response = await page.request.get(`${API}/design`, { headers })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).design.plate_layout
}
