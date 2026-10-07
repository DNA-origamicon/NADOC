import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const originalHref = location.href
const stickyKey = 'nadoc:tab-doc'
let originalSticky

beforeEach(() => {
  originalSticky = sessionStorage.getItem(stickyKey)
  sessionStorage.removeItem(stickyKey)
  vi.resetModules()
})

afterEach(() => {
  history.replaceState(null, '', originalHref)
  if (originalSticky == null) sessionStorage.removeItem(stickyKey)
  else sessionStorage.setItem(stickyKey, originalSticky)
  vi.resetModules()
})

async function at(path) {
  history.replaceState(null, '', path)
  return import('./doc_id.js')
}

describe('document identity across editor handoffs', () => {
  it('keeps a standalone cadnano editor on the default document', async () => {
    sessionStorage.setItem(stickyKey, 'unrelated-main-tab')
    const identity = await at('/cadnano-editor.html')
    expect(identity.getDocId()).toBeNull()
    expect(identity.hasExplicitDoc()).toBe(false)
    expect(identity.docHeaders()).toEqual({})
    expect(identity.docKey('nadoc:design')).toBe('nadoc:design')
  })

  it('normalizes an explicit main-view default sentinel without minting or losing the URL', async () => {
    sessionStorage.setItem(stickyKey, 'unrelated-main-tab')
    const identity = await at('/?doc=__default__&readiness=simulation')
    expect(identity.getDocId()).toBeNull()
    expect(identity.hasExplicitDoc()).toBe(false)
    expect(identity.docHeaders()).toEqual({})
    expect(identity.docKey('nadoc:design')).toBe('nadoc:design')
    expect(new URL(location.href).searchParams.get('doc')).toBe('__default__')
    expect(sessionStorage.getItem(stickyKey)).toBe('unrelated-main-tab')
  })

  it('still mints and pins a sticky identity for an ordinary main-app tab', async () => {
    const identity = await at('/?new=part')
    const id = identity.getDocId()
    expect(id).toBeTruthy()
    expect(id).not.toBe('__default__')
    expect(identity.hasExplicitDoc()).toBe(true)
    expect(identity.docHeaders()).toEqual({ 'X-NADOC-Doc': id })
    expect(identity.docKey('nadoc:design')).toBe(`nadoc:design:${id}`)
    expect(sessionStorage.getItem(stickyKey)).toBe(id)
    const params = new URL(location.href).searchParams
    expect(params.get('doc')).toBe(id)
    expect(params.get('new')).toBe('part')
  })

  it('preserves ordinary explicit identities and their storage/header scope', async () => {
    sessionStorage.setItem(stickyKey, 'other')
    const identity = await at('/?doc=shared-arm')
    expect(identity.getDocId()).toBe('shared-arm')
    expect(identity.docHeaders()).toEqual({ 'X-NADOC-Doc': 'shared-arm' })
    expect(identity.docKey('nadoc:design')).toBe('nadoc:design:shared-arm')
    expect(sessionStorage.getItem(stickyKey)).toBe('other')
  })
})
