// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { initTorqueDriveSites } from './torque_drive_sites.js'

it('reuses anchor highlight-all, row focus, empty-space reset and read-only inspection', () => {
  document.body.innerHTML = '<div id="drive"></div>'
  const mount = document.querySelector('#drive')
  let editable = true
  const onChange = vi.fn(), highlight = vi.fn()
  window.addEventListener('nadoc:anchors-change', highlight)
  const picker = initTorqueDriveSites({ mount, canEdit: () => editable, onChange })
  const refs = [{ kind: 'strand', id: 'one' }, { kind: 'strand', id: 'two' }]
  picker.apply(refs)
  expect(mount.querySelectorAll('[data-hl]')).toHaveLength(2)
  expect(onChange).not.toHaveBeenCalled()
  const glow = mount.querySelector('[type=checkbox]')
  glow.click()
  expect(mount.querySelectorAll('[data-hl]')).toHaveLength(0)
  mount.querySelector('tr').click()
  expect(mount.querySelectorAll('[data-hl]')).toHaveLength(1)
  expect(highlight.mock.calls.at(-1)[0].detail.highlighted).toEqual([refs[0]])
  mount.querySelector('tr').click()
  expect(mount.querySelectorAll('[data-hl]')).toHaveLength(0)
  glow.click()
  mount.querySelector('tr').click()
  mount.querySelector('.oxdna-driven-sites-list').click()
  expect(mount.querySelectorAll('[data-hl]')).toHaveLength(2)
  editable = false
  picker.refresh()
  expect(glow.disabled).toBe(false)
  mount.querySelector('[data-role=remove]').click()
  expect(mount.querySelectorAll('tr')).toHaveLength(2)
  mount.querySelector('tr').click()
  expect(mount.querySelectorAll('[data-hl]')).toHaveLength(1)
  expect(onChange).not.toHaveBeenCalled()
  editable = true
  picker.refresh()
  mount.querySelector('[data-role=remove]').click()
  expect(onChange).toHaveBeenLastCalledWith([refs[1]])
  picker.apply([])
  expect(mount.textContent).toContain('All unanchored particles')
  window.removeEventListener('nadoc:anchors-change', highlight)
})
