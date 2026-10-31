import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('create domain cluster from selection including rendered extension tail', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: 'e2e-domain-cluster', name: 'domain-cluster' })
  const expected = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const t = window.__nadocTest
    const strand = t.store.getState().currentDesign.strands.find(s => s.domains.length)
    await api.createStrandExtension(strand.id, 'three_prime', { sequence: 'TTTTT' })
    const entries = t.getDesignRenderer().getBackboneEntries().filter(e => e.nuc.strand_id === strand.id)
    const indices = [...new Set(entries.map(e => e.nuc.domain_index))]
    if (!indices.includes(strand.domains.length)) throw new Error('Tail geometry missing')
    t.store.setState({ selection: { context: 'design', level: 'domain',
      items: indices.map(domainIndex => ({ kind: 'domain', strandId: strand.id, domainIndex })) } })
    return strand.domains.map((_, domain_index) => ({ strand_id: strand.id, domain_index }))
  })
  await page.locator('#right-tab-strip [data-tab="clustering"]').click()
  const pending = page.waitForResponse(r => r.url().endsWith('/api/design/cluster') && r.request().method() === 'POST')
  await page.locator('#cluster-new-btn').click()
  const response = await pending
  expect(response.status()).toBe(200)
  const cluster = (await response.json()).design.cluster_transforms.at(-1)
  expect(cluster.domain_ids).toEqual(expected)
  await expect(page.locator('#cluster-list')).toContainText(cluster.name)
  expect(errors).toEqual([])
})
