// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSharedPanelViews, enableSharedPanelStyles, sharedPanelSelector } from './shared_panel_views.js'
let shared
let mounts = []
afterEach(() => { mounts.forEach(m => m.dispose()); mounts = []; shared?.dispose(); document.body.innerHTML = '' })
function setup() {
  document.body.innerHTML = '<div id="parking"><section id="source"><label for="value">Value</label><input id="value" value="one"><button id="action">Act</button><input id="toggle" type="checkbox"></section></div><div id="a"></div><div id="b"></div>'
  const source = document.getElementById('source')
  shared = createSharedPanelViews(source, document.getElementById('parking'))
  const a = document.getElementById('a'), b = document.getElementById('b')
  mounts.push(shared.mount(a), shared.mount(b))
  return { source, a, b }
}
describe('shared panel views', () => {
  it('keeps unique IDs and local label associations', () => {
    const { b } = setup()
    expect(document.querySelectorAll('#value')).toHaveLength(1)
    expect(b.querySelector('label').htmlFor).toBe(b.querySelector('input').id)
  })
  it('reflects values, checked state and dynamically added content', async () => {
    const { source, b } = setup()
    source.querySelector('input').value = 'two'
    source.querySelector('#toggle').checked = true
    shared.flush()
    expect(b.querySelector('input').value).toBe('two')
    expect(b.querySelector('input[type=checkbox]').checked).toBe(true)
    source.append(document.createElement('select'))
    await Promise.resolve(); shared.flush()
    expect(b.querySelector('select')).not.toBeNull()
  })
  it('keeps controls attached while status text and attributes update', async () => {
    const { source, b } = setup()
    const input = b.querySelector('input')
    source.querySelector('button').textContent = 'Updated status'
    source.querySelector('button').disabled = true
    await Promise.resolve(); shared.flush()
    expect(b.querySelector('input')).toBe(input)
    expect(input.isConnected).toBe(true)
    expect(b.querySelector('button').textContent).toBe('Updated status')
    expect(b.querySelector('button').disabled).toBe(true)
  })

  it('routes activation through the single existing listener, once', () => {
    const { source, b } = setup()
    const action = vi.fn()
    source.querySelector('button').addEventListener('click', action)
    b.querySelector('button').click()
    expect(action).toHaveBeenCalledOnce()
    expect(b.contains(source)).toBe(true)
    expect(document.querySelectorAll('#action')).toHaveLength(1)
  })
  it('retains independent scroll offsets when live controls move', () => {
    const { source, a, b } = setup()
    a.scrollTop = 100; b.scrollTop = 400
    source.scrollTop = 20
    b.querySelector('section').scrollTop = 60
    mounts[1].activate()
    expect(source.scrollTop).toBe(60)
    expect(a.querySelector('section').scrollTop).toBe(20)
    expect(a.scrollTop).toBe(100); expect(b.scrollTop).toBe(400)
    mounts[0].activate()
    expect(source.scrollTop).toBe(20)
  })
  it('retains live controls when one copy closes and parks them when all close', () => {
    const { source, b } = setup()
    mounts[0].dispose()
    expect(b.contains(source)).toBe(true)
    mounts[1].dispose(); mounts = []
    expect(source.parentElement.id).toBe('parking')
    expect(source.hidden).toBe(true)
  })
  it('applies ID-based panel styling to namespaced copies', () => {
    const style = document.createElement('style'); style.textContent = '#source #value { color: red; }'
    document.head.append(style)
    setup(); enableSharedPanelStyles()
    expect(style.sheet.cssRules[0].selectorText).toContain('[data-sidebar-source-id="value"]')
    style.remove()
  })
})

it('leaves attribute hashes intact while extending ID selectors', () => {
  expect(sharedPanelSelector('#source [style*="color:#fff"]')).toBe(':is(#source, [data-sidebar-source-id="source"]) [style*="color:#fff"]')
})
