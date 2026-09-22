// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { mountImageClearanceReview } from './md_image_clearance_review.js'

describe('image clearance review', () => {
  it('shows a measured pass without asking for an override', () => {
    const container = document.createElement('div'), button = document.createElement('button')
    const view = mountImageClearanceReview(container, { status: 'pass', axis_gaps_nm: [2.4, 3, 4], recommended_gap_nm: 2.4,
      detail: 'Fixed pose only.', coordinate_source: 'equilibrated.coor', cell_source: 'equilibrated.xsc' }, button)
    expect(view.canSubmit()).toBe(true)
    expect(view.overridden()).toBe(false)
    expect(button.disabled).toBe(false)
    expect(container.textContent).toContain('2.40 / 3.00 / 4.00 nm')
    expect(container.textContent).toContain('equilibrated.coor')
  })
  it('renders diagnostics as text and blocks unknown data', () => {
    const container = document.createElement('div'), button = document.createElement('button')
    const view = mountImageClearanceReview(container, { status: 'unknown', detail: '<img src=x onerror=alert(1)>' }, button)
    expect(container.querySelector('img')).toBeNull()
    expect(view.canSubmit()).toBe(false)
    const checkbox = container.querySelector('input')
    checkbox.click()
    expect(view.overridden()).toBe(true)
    checkbox.click()
    expect(button.disabled).toBe(true)
  })
})
