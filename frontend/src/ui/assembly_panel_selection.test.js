import { it, expect } from 'vitest'
import { paintAssemblyPanelSelection } from './assembly_panel_selection.js'

it('repaints selection while preserving row controls and expanded connector content', () => {
  const root = document.createElement('div')
  root.innerHTML = '<div data-instance-id="a"><select><option>Full</option></select></div><div data-instance-id="b"></div><div data-group-id="g"></div>'
  const control = root.querySelector('select'), [a, b, g] = root.children
  expect(paintAssemblyPanelSelection(root, { activeInstanceId: 'a', multiSelectedInstanceIds: ['b'], activeGroupId: 'g' })).toBe(a)
  expect(a.style.background).toBe('rgb(30, 58, 95)')
  expect(b.style.background).toBe('rgb(25, 44, 69)')
  expect(g.style.borderLeftColor).toBe('rgb(139, 92, 246)')
  paintAssemblyPanelSelection(root, {})
  expect(a.style.background).toBe('transparent')
  expect(root.querySelector('select')).toBe(control)
})
