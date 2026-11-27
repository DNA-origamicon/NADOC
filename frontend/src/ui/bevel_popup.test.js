// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createBevelPopup } from './bevel_popup.js'

let popup
afterEach(() => { popup?.dispose(); document.body.replaceChildren() })
function setup() {
  const handlers = { onChange: vi.fn(), onCancel: vi.fn(), onApply: vi.fn(), onSelect: vi.fn() }
  popup = createBevelPopup(handlers)
  popup.open()
  return handlers
}
function input(id, value) {
  const node = document.getElementById(`bevel-${id}`)
  node.value = String(value)
  node.dispatchEvent(new Event('input', { bubbles: true }))
  return node
}

it('starts awaiting a cluster and uses the shared NADOC popup and buttons', () => {
  const handlers = setup()
  expect(document.querySelector('.tool-popup__header h2').textContent).toBe('Bevel')
  expect(document.querySelector('fieldset').disabled).toBe(true)
  expect(document.querySelector('.def-btn.primary').disabled).toBe(true)
  document.querySelector('[aria-label="Close Bevel"]').click()
  expect(handlers.onCancel).toHaveBeenCalledOnce()
})

it.each([['SQUARE', 8, 2.672], ['HONEYCOMB', 7, 2.338]])('links position units and increments for %s', (lattice, step, nm) => {
  const handlers = setup()
  popup.selected('Selected cluster', lattice, { positionBp: 40, angleDeg: 0, directionDeg: 0, trimEnd: 'end' })
  expect(document.getElementById('bevel-positionBp').step).toBe(String(step))
  expect(Number(document.getElementById('bevel-positionNm').step)).toBeCloseTo(nm)
  expect(document.getElementById('bevel-angleDeg').step).toBe('15')
  expect(document.getElementById('bevel-directionDeg').step).toBe('15')
  input('positionNm', 2.672)
  expect(handlers.onChange).toHaveBeenLastCalledWith({ positionBp: 8, angleDeg: 0, directionDeg: 0, trimEnd: 'end' })
  input('directionDeg', -15)
  expect(handlers.onChange).toHaveBeenLastCalledWith({ positionBp: 8, angleDeg: 0, directionDeg: 345, trimEnd: 'end' })
})

it('disables Apply for a stale or invalid preview and shows only reported progress', () => {
  const handlers = setup()
  popup.selected('Cluster', 'SQUARE', { positionBp: 40, angleDeg: 0, directionDeg: 0, trimEnd: 'end' })
  popup.ready('Full preview ready')
  expect(document.querySelector('.def-btn.primary').disabled).toBe(false)
  input('angleDeg', 180)
  expect(handlers.onChange).not.toHaveBeenCalled()
  expect(document.querySelector('.def-btn.primary').disabled).toBe(true)
  popup.ready('Obsolete result')
  expect(document.querySelector('.def-btn.primary').disabled).toBe(true)
  popup.calculating(35, 'Routing staples')
  expect(document.querySelector('progress').value).toBe(35)
  expect(document.querySelector('[role=status]').textContent).toBe('35% — Routing staples')
  popup.calculating(null, 'Preparing')
  expect(document.querySelector('progress').hasAttribute('value')).toBe(false)
  popup.error('AGENT_PROCESS_REQUIRED: junction authoring path is unavailable')
  expect(document.querySelector('progress').hidden).toBe(true)
  expect(document.querySelector('.def-btn.primary').disabled).toBe(true)
})

it.each([['HONEYCOMB', 7], ['SQUARE', 8]])('steps from an arbitrary typed position and angle for %s', (lattice, step) => {
  const handlers = setup()
  popup.selected('Cluster', lattice, { positionBp: 83, angleDeg: 55, directionDeg: 7, trimEnd: 'end' })
  function spin(name, up = true) {
    const node = document.getElementById(`bevel-${name}`)
    if (up) node.stepUp()
    else node.stepDown()
    node.dispatchEvent(new Event('input', { bubbles: true }))
  }
  spin('positionBp')
  expect(handlers.onChange).toHaveBeenLastCalledWith({ positionBp: 83 + step, angleDeg: 55, directionDeg: 7, trimEnd: 'end' })
  spin('positionNm', false)
  expect(handlers.onChange).toHaveBeenLastCalledWith({ positionBp: 83, angleDeg: 55, directionDeg: 7, trimEnd: 'end' })
  spin('angleDeg')
  spin('directionDeg')
  expect(handlers.onChange).toHaveBeenLastCalledWith({ positionBp: 83, angleDeg: 70, directionDeg: 22, trimEnd: 'end' })
  input('angleDeg', 5)
  spin('angleDeg', false)
  expect(document.getElementById('bevel-angleDeg').value).toBe('5')
  input('positionBp', 82)
  spin('positionBp', false)
  expect(handlers.onChange).toHaveBeenLastCalledWith({ positionBp: 82 - step, angleDeg: 5, directionDeg: 22, trimEnd: 'end' })
})

it('invalidates the preview when the removed end changes', () => {
  const handlers = setup()
  popup.selected('Bundle', 'SQUARE', { positionBp: 42, angleDeg: 30, directionDeg: 0, trimEnd: 'end' })
  popup.ready('Ready')
  const end = document.getElementById('bevel-trimEnd')
  end.value = 'start'; end.dispatchEvent(new Event('change'))
  expect(handlers.onChange).toHaveBeenLastCalledWith({ positionBp: 42, angleDeg: 30, directionDeg: 0, trimEnd: 'start' })
  expect(document.querySelector('.def-btn.primary').disabled).toBe(true)
})
