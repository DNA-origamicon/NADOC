import { afterEach, describe, expect, it, vi } from 'vitest'
import { showGenerateDesign } from './generate_design.js'

const plan = {
  revision: 17, doc_id: 'part-a', center_distance_nm: 40, lattice_type: 'SQUARE',
  alternatives: [{ scaffold_size: 7249, section: '4 × 6', helix_count: 24, length_nm: 90, scaffold_used_nt: 7200 }],
  selected: { unused_scaffold_nt: 49 }, reason: '7249 is sufficient.', attachment_status: 'Reach checked during generation.',
}
function setup(overrides = {}) {
  const store = { getState: () => ({ currentDesign: { nanoparticles: [{ kind: 'gold_nanosphere' }, { kind: 'gold_nanosphere' }] }, ...overrides }) }
  const api = { planGeneratedDesign: vi.fn(async () => plan), generateDesign: vi.fn(async () => ({ generation: { connections: [{ reused: true }, { reused: false }] } })), lastErrorMessage: () => 'Centers are unreachable.' }
  const modal = showGenerateDesign({ api, store })
  return { api, modal }
}
const button = text => [...document.querySelectorAll('button')].find(b => b.textContent === text)
const flush = async () => { await new Promise(resolve => setTimeout(resolve, 0)) }
afterEach(() => { document.body.replaceChildren() })

describe('Generate design', () => {
  it('shows budgets and commits the exact reviewed revision and document', async () => {
    const { api, modal } = setup()
    await flush()
    expect(document.body.textContent).toContain('49 scaffold bases remain unrouted')
    button('Generate in current loadout').click()
    await flush()
    expect(api.generateDesign).toHaveBeenCalledWith({ roll_deg: 0, duplex_bp: 18, extend_rod: true }, 17, 'part-a')
    expect(document.body.textContent).toContain('Both particle centers are unchanged')
    expect(button('Generate in current loadout').disabled).toBe(true)
    modal.close()
  })
  it('invalidates the plan when either setting changes and rejects invalid lengths', async () => {
    const { api, modal } = setup()
    await flush()
    const length = document.querySelector('[aria-label="New duplex length (bp)"]')
    length.value = '18.5'
    length.dispatchEvent(new Event('input'))
    expect(button('Generate in current loadout').disabled).toBe(true)
    button('Calculate design').click()
    await flush()
    expect(api.planGeneratedDesign).toHaveBeenCalledTimes(1)
    expect(document.body.textContent).toContain('integer duplex length')
    modal.close()
  })
  it('displays failed reach checks without offering a stale second commit', async () => {
    const { api, modal } = setup()
    await flush()
    api.generateDesign.mockResolvedValue(null)
    button('Generate in current loadout').click()
    await flush()
    expect(document.body.textContent).toContain('Centers are unreachable')
    expect(button('Generate in current loadout').disabled).toBe(true)
    modal.close()
  })
  it.each([{ assemblyActive: true }, { currentDesign: null }])('blocks unsupported document states %j', async overrides => {
    const { api, modal } = setup(overrides)
    await flush()
    expect(api.planGeneratedDesign).not.toHaveBeenCalled()
    expect(button('Calculate design').disabled).toBe(true)
    modal.close()
  })
  it.each([3, 4])('offers a platform for %i particles in the current loadout', async count => {
    const { api, modal } = setup({ currentDesign: { nanoparticles: Array.from({ length: count }, () => ({ kind: 'gold_nanosphere' })) } })
    api.generateDesign.mockResolvedValue({ generation: { connections: Array.from({ length: count }, () => ({ reused: false })) } })
    await flush()
    expect(document.body.textContent).toContain(`solid platform for the ${count} gold nanoparticles`)
    expect(document.querySelector('[aria-label="Platform rotation within fitted plane (degrees)"]')).not.toBeNull()
    expect(document.body.textContent).toContain('Maximum distance from fitted plane')
    button('Generate in current loadout').click()
    await flush()
    expect(document.body.textContent).toContain(`Added ${count} connections to the current loadout`)
    expect(document.body.textContent).toContain('All particle centers are unchanged')
    modal.close()
  })
  it.each([1, 5])('rejects unsupported particle count %i', async count => {
    const { api, modal } = setup({ currentDesign: { nanoparticles: Array.from({ length: count }, () => ({ kind: 'gold_nanosphere' })) } })
    await flush()
    expect(api.planGeneratedDesign).not.toHaveBeenCalled()
    expect(button('Calculate design').disabled).toBe(true)
    modal.close()
  })
})
