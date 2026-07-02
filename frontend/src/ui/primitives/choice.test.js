import { describe, it, expect, afterEach } from 'vitest'
import { showChoice } from './choice.js'

const btnByText = (t) => [...document.querySelectorAll('button')].find(b => b.textContent.includes(t))

describe('showChoice', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('renders each option (with tooltip) and resolves to the clicked option value', async () => {
    const p = showChoice({
      title: 'Pick', message: 'Choose one',
      options: [
        { value: 'a', label: 'Alpha', tooltip: 'the first letter' },
        { value: 'b', label: 'Beta' },
        { value: 'c', label: 'Gamma' },
      ],
    })
    expect(btnByText('Alpha')).toBeTruthy()
    expect(btnByText('Alpha').title).toBe('the first letter')   // long description on hover
    expect(btnByText('Gamma')).toBeTruthy()
    btnByText('Beta').click()
    await expect(p).resolves.toBe('b')
  })

  it('resolves to null when cancelled', async () => {
    const p = showChoice({ options: [{ value: 'a', label: 'Alpha' }], cancelLabel: 'Cancel' })
    btnByText('Cancel').click()
    await expect(p).resolves.toBe(null)
  })
})
