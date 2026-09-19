// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { beginPanelLoading, recordPanelRequest } from './panel_loading.js'

describe('panel loading feedback', () => {
  it('keeps the spinner until all overlapping work finishes', () => {
    const target = document.createElement('button')
    const first = beginPanelLoading([target, target])
    const second = beginPanelLoading([target])
    expect(target.querySelectorAll('[role="status"]')).toHaveLength(1)
    first(); first()
    expect(target.getAttribute('aria-busy')).toBe('true')
    second()
    expect(target.children).toHaveLength(0)
    expect(target.hasAttribute('aria-busy')).toBe(false)
  })

  it('clears failed and aborted requests without clearing another engine', () => {
    document.body.innerHTML = '<button class="left-tab-btn" data-tab="dynamics"></button><button class="engine-selector-btn" data-engine="namd"></button><button id="simulate-jobs-toggle"></button>'
    recordPanelRequest({ id: 'a', phase: 'start', path: '/md/jobs' })
    recordPanelRequest({ id: 'b', phase: 'start', path: '/simulate/jobs?design_source_path=x' })
    recordPanelRequest({ id: 'a', phase: 'error' })
    expect(document.querySelector('[data-engine]').hasAttribute('aria-busy')).toBe(false)
    expect(document.querySelector('[data-tab]').getAttribute('aria-busy')).toBe('true')
    recordPanelRequest({ id: 'b', phase: 'aborted' })
    expect(document.querySelectorAll('[data-panel-loading]')).toHaveLength(0)
  })
})
