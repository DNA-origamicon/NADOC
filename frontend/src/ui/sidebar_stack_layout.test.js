import { describe, expect, it } from 'vitest'
import { sidebarBudget, fitSidebarWidths } from './sidebar_stack_layout.js'
describe('sidebar capacity', () => {
  it('reserves the right controls, strips and a usable 3D workspace', () => {
    expect(sidebarBudget(1280, 300, 80)).toBe(580)
    expect(sidebarBudget(500, 300, 80)).toBe(0)
  })
  it('narrows panels before closing excess rightmost copies', () => {
    expect(fitSidebarWidths([280, 280], 450)).toEqual([250, 200])
    expect(fitSidebarWidths([280, 280, 280], 450)).toEqual([250, 200])
    expect(fitSidebarWidths([280], 150)).toEqual([])
  })
  it('normalizes corrupt stored widths', () => {
    expect(fitSidebarWidths([null, 5000, -2], 2000)).toEqual([280, 600, 200])
  })
})
