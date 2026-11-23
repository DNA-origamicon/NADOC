import { expect, it } from 'vitest'
import { slabInCluster } from './slab_cluster_scope.js'
it('scopes extension slabs to their terminal domain rather than their synthetic helix', () => {
  const n = { helix_id: '__ext_tail', extension_id: 'tail' }
  const helices = new Set(['h']), parents = new Map([['tail','h']]), domains = new Map([['tail','s:2']])
  const check = (selected, baseKeys = null, force = false) => slabInCluster(n, helices, () => false, parents, domains, selected, baseKeys, force)
  expect(check(null)).toBe(true)
  expect(check(new Set(['s:1']))).toBe(false)
  expect(check(new Set(['s:2']))).toBe(true)
  expect(check(new Set(['s:1']), null, true)).toBe(true)
  expect(check(null, new Set(['h:0:FORWARD']))).toBe(false)
})
