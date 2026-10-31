import { afterEach, expect, it } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initRootExemptionNotice } from './root_exemption_notice.js'

let panel
afterEach(() => { panel?.dispose(); panel = null; document.body.replaceChildren() })

it('shows explicit exemptions as text, refreshes and clears with the design', () => {
  const store = createMockStore({ currentDesign: {}, validationReport: null })
  panel = initRootExemptionNotice({ store, host: document.body })
  const section = document.querySelector('.root-length-exemptions')
  expect(section.hidden).toBe(true)
  store.setState({ validationReport: { passed: true,
    exemptions: [{ message: 'Root-length preservation exemption: <strain>. Existing strain is retained.' }] } })
  expect(section.hidden).toBe(false)
  expect(section.textContent).toContain('<strain>')
  expect(document.querySelector('strain')).toBeNull()
  store.setState({ currentDesign: null })
  expect(section.hidden).toBe(true)
  panel.dispose()
  store.setState({ currentDesign: {} })
  expect(document.querySelector('.root-length-exemptions')).toBeNull()
})
