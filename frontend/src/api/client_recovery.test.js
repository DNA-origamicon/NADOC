/**
 * Recovery-cache quota management (api/client.js).
 *
 * Regression: closed tabs leak per-document `nadoc:design:<id>` /
 * `nadoc:assembly:<id>` full-snapshot entries into localStorage (the sticky doc
 * id lived in sessionStorage and died with the tab). They accumulate until the
 * quota is exhausted and every setItem throws — surfacing as "exceeded the quota"
 * when opening a part. The fix evicts OTHER documents' snapshots under pressure
 * and retries the write once.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { evictOtherDocRecoverySnapshots, persistDesign } from './client.js'
import { docKey } from '../shared/doc_id.js'
import { store } from '../state/store.js'

const OTHER = 'otherdoc0000000000000000000000ff'

beforeEach(() => localStorage.clear())
afterEach(() => {
  localStorage.clear()
  store.setState({ currentDesign: null })
})

describe('evictOtherDocRecoverySnapshots', () => {
  it('drops other documents’ design/assembly snapshots, keeps mine + unrelated keys', () => {
    localStorage.setItem(docKey('nadoc:design'), 'MINE')          // my snapshot
    localStorage.setItem(docKey('nadoc:assembly'), 'MINE-ASM')   // my snapshot
    localStorage.setItem(`nadoc:design:${OTHER}`, 'x'.repeat(50)) // leaked orphan
    localStorage.setItem(`nadoc:assembly:${OTHER}`, 'y'.repeat(50)) // leaked orphan
    localStorage.setItem(`nadoc:design-filename:${OTHER}`, 'foo') // NOT a snapshot base → keep
    localStorage.setItem('nadoc:mode', 'assembly')               // unrelated → keep

    const removed = evictOtherDocRecoverySnapshots()

    expect(removed).toBe(2)
    expect(localStorage.getItem(`nadoc:design:${OTHER}`)).toBeNull()
    expect(localStorage.getItem(`nadoc:assembly:${OTHER}`)).toBeNull()
    expect(localStorage.getItem(docKey('nadoc:design'))).toBe('MINE')
    expect(localStorage.getItem(docKey('nadoc:assembly'))).toBe('MINE-ASM')
    expect(localStorage.getItem(`nadoc:design-filename:${OTHER}`)).toBe('foo')
    expect(localStorage.getItem('nadoc:mode')).toBe('assembly')
  })

  it('does not confuse `nadoc:design-filename:<id>` with the `nadoc:design` base (prefix collision)', () => {
    localStorage.setItem(`nadoc:design-filename:${OTHER}`, 'keep-me')
    expect(evictOtherDocRecoverySnapshots()).toBe(0)
    expect(localStorage.getItem(`nadoc:design-filename:${OTHER}`)).toBe('keep-me')
  })

  it('returns 0 when there are no foreign snapshots', () => {
    localStorage.setItem(docKey('nadoc:design'), 'MINE')
    expect(evictOtherDocRecoverySnapshots()).toBe(0)
    expect(localStorage.getItem(docKey('nadoc:design'))).toBe('MINE')
  })
})

describe('persistDesign quota recovery', () => {
  it('evicts other docs and retries once when the first write throws quota', () => {
    store.setState({ currentDesign: { id: 'd1', helices: [] } })
    localStorage.setItem(`nadoc:design:${OTHER}`, 'x'.repeat(100))

    let calls = 0
    const real = Storage.prototype.setItem
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (k, v) {
      calls += 1
      if (calls === 1) {
        const err = new Error('exceeded the quota')
        err.name = 'QuotaExceededError'
        throw err
      }
      return real.call(this, k, v)
    })

    persistDesign()

    // First write threw → eviction dropped the orphan → second write succeeded.
    expect(localStorage.getItem(`nadoc:design:${OTHER}`)).toBeNull()
    expect(localStorage.getItem(docKey('nadoc:design'))).toBe(JSON.stringify({ id: 'd1', helices: [] }))
    spy.mockRestore()
  })

  it('swallows the failure (no throw) when eviction frees nothing', () => {
    store.setState({ currentDesign: { id: 'd2' } })
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      const err = new Error('exceeded the quota'); err.name = 'QuotaExceededError'; throw err
    })
    // No foreign snapshots to evict → retry path not taken → must NOT throw.
    expect(() => persistDesign()).not.toThrow()
    spy.mockRestore()
  })
})
