import { describe, it, expect, beforeEach } from 'vitest'
import { mountIds, clearDom } from './factory_dom.js'

beforeEach(() => clearDom())

describe('mountIds', () => {
  it('creates one element per id (array form, default div) findable by getElementById', () => {
    mountIds(['a', 'b'])
    expect(document.getElementById('a')?.tagName).toBe('DIV')
    expect(document.getElementById('b')?.tagName).toBe('DIV')
  })

  it('honors per-id tag names (object form)', () => {
    mountIds({ 'menu-view-fret': 'button', 'slider': 'input', 'list': 'div' })
    expect(document.getElementById('menu-view-fret')?.tagName).toBe('BUTTON')
    expect(document.getElementById('slider')?.tagName).toBe('INPUT')
    expect(document.getElementById('list')?.tagName).toBe('DIV')
  })

  it('returns an id→element map', () => {
    const els = mountIds(['x'])
    expect(els.x).toBe(document.getElementById('x'))
  })

  it('respects a custom defaultTag', () => {
    mountIds(['btn1', 'btn2'], { defaultTag: 'button' })
    expect(document.getElementById('btn1')?.tagName).toBe('BUTTON')
  })

  it('resets the body so a second mount does not accumulate', () => {
    mountIds(['a'])
    mountIds(['b'])
    expect(document.getElementById('a')).toBeNull()
    expect(document.getElementById('b')).toBeTruthy()
  })
})
