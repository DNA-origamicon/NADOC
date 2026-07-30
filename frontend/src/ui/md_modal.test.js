import { describe, it, expect, afterEach } from 'vitest'
import { openChoiceModal } from './md_modal.js'

describe('openChoiceModal', () => {
  afterEach(() => { document.body.innerHTML = '' })

  const spec = (over = {}) => ({
    testid: 'test-modal',
    title: 'A question',
    lines: ['line one', 'line two'],
    choices: [
      { label: 'No', value: 'no', choice: 'no' },
      { label: 'Yes', value: 'yes', choice: 'yes', primary: true },
    ],
    ...over,
  })
  const modal = () => document.querySelector('[data-testid="test-modal"]')
  const btn = (c) => document.querySelector(`[data-testid="test-modal"] button[data-choice="${c}"]`)

  it('renders the title, every line, and every choice', () => {
    openChoiceModal(spec())
    expect(modal().textContent).toContain('A question')
    expect(modal().textContent).toContain('line one')
    expect(modal().textContent).toContain('line two')
    expect(btn('no').textContent).toBe('No')
    expect(btn('yes').textContent).toBe('Yes')
  })

  it("resolves the chosen option's value and removes itself", async () => {
    const p = openChoiceModal(spec())
    btn('yes').click()
    await expect(p).resolves.toBe('yes')
    expect(modal()).toBeNull()
  })

  it('resolves dismissValue on Escape', async () => {
    const p = openChoiceModal(spec({ dismissValue: 'dismissed' }))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(p).resolves.toBe('dismissed')
  })

  it('resolves dismissValue on a backdrop click, but not on a click inside the box', async () => {
    const p = openChoiceModal(spec({ dismissValue: 'dismissed' }))
    modal().firstChild.click()            // inside the box — must NOT dismiss
    expect(modal()).toBeTruthy()
    modal().click()                       // the overlay itself
    await expect(p).resolves.toBe('dismissed')
  })

  it('only ever resolves once', async () => {
    const p = openChoiceModal(spec())
    const yes = btn('yes')
    yes.click()
    yes.click()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(p).resolves.toBe('yes')
  })

  it('copies extra dataset keys onto the overlay', () => {
    openChoiceModal(spec({ dataset: { tier: 'a2', helices: '2' } }))
    expect(modal().dataset.tier).toBe('a2')
    expect(modal().dataset.helices).toBe('2')
  })
})
