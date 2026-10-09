import { afterEach, describe, expect, it, vi } from 'vitest'
import { showGenerateDesign } from './generate_design.js'

const plan = {
  revision: 17, doc_id: 'part-a', center_distance_nm: 40, lattice_type: 'SQUARE',
  alternatives: [{ scaffold_size: 7249, section: '4 × 6', helix_count: 24, length_nm: 90, scaffold_used_nt: 7200 }],
  selected: { unused_scaffold_nt: 49 }, reason: '7249 is sufficient.', attachment_status: 'Reach checked during generation.',
}
function setup(overrides = {}, planOverrides = {}) {
  const store = { getState: () => ({ currentDesign: { nanoparticles: [{ kind: 'gold_nanosphere' }, { kind: 'gold_nanosphere' }] }, ...overrides }) }
  const api = { planGeneratedDesign: vi.fn(async () => ({ ...plan, ...planOverrides })), generateDesign: vi.fn(async () => ({ generation: { connections: [{ reused: true }, { reused: false }] } })), lastErrorMessage: () => 'Centers are unreachable.' }
  const modal = showGenerateDesign({ api, store })
  return { api, modal }
}
const button = text => [...document.querySelectorAll('button')].find(b => b.textContent === text)
const flush = async () => { await new Promise(resolve => setTimeout(resolve, 0)) }
afterEach(() => { document.body.replaceChildren() })

it('reviews the per-particle connection count and displays the automatic CanDo result', async () => {
  const { api } = setup()
  await flush()
  const count = document.querySelector('[aria-label="Connections per nanoparticle"]')
  expect([...count.options].map(o => o.value)).toEqual(['1', '2', '3'])
  count.value = '3'; count.dispatchEvent(new Event('change'))
  expect(button('Generate in current loadout').disabled).toBe(true)
  button('Calculate design').click(); await flush()
  expect(api.planGeneratedDesign.mock.lastCall[0].connections_per_particle).toBe(3)
  api.generateDesign.mockResolvedValue({ generation: {
    connections: Array.from({ length: 6 }, () => ({ reused: false })),
    structural_validation: { status: 'warning', max_rmsf_nm: 6, warnings: ['Inspect flexibility.'] },
  } })
  button('Generate in current loadout').click(); await flush()
  expect(api.generateDesign.mock.lastCall[0].connections_per_particle).toBe(3)
  expect(document.body.textContent).toContain('Added 6 connections')
  expect(document.body.textContent).toContain('CanDo structural check: warning')
  expect(document.body.textContent).toContain('Inspect flexibility.')
})

describe('Generate design', () => {
  it('shows budgets and commits the exact reviewed revision and document', async () => {
    const { api, modal } = setup()
    await flush()
    expect(document.querySelector('[role="status"]').title).toContain('49 scaffold bases remain unrouted')
    button('Generate in current loadout').click()
    await flush()
    expect(api.generateDesign).toHaveBeenCalledWith({ roll_deg: 0, duplex_bp: 18, extend_rod: true }, 17, 'part-a', expect.any(Function))
    expect(document.body.textContent).toContain('Particle centers preserved')
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
    const { api, modal } = setup({ currentDesign: { nanoparticles: Array.from({ length: count }, () => ({ kind: 'gold_nanosphere' })) } }, {
      perimeter_alignment: { aligned_edges: count, edges: Array(count).fill({}), tolerance_deg: 5, target_edges: count === 3 ? 1 : 2 },
    })
    api.generateDesign.mockResolvedValue({ generation: { connections: Array.from({ length: count }, () => ({ reused: false })) } })
    await flush()
    expect(document.body.textContent).toContain(`${count} gold nanoparticles`)
    expect(document.querySelector('[aria-label="Platform rotation within fitted plane (degrees)"]')).not.toBeNull()
    expect(document.querySelector('[role="status"]').title).toContain(`Perimeter alignment: ${count} edges within 5°`)
    expect(document.querySelector('[aria-label="Platform rotation within fitted plane (degrees)"]').title).toContain('perimeter edge')
    button('Generate in current loadout').click()
    await flush()
    expect(document.body.textContent).toContain(`Added ${count} connections`)
    expect(document.body.textContent).toContain('Particle centers preserved')
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

describe('Curved rod generation', () => {
  const particles = Array.from({ length: 4 }, (_, i) => ({ id: `np-${i}`, kind: 'gold_nanosphere', name: `Gold ${i + 1}` }))
  function chooseCurve() {
    const shape = document.querySelector('[aria-label="Design shape"]')
    shape.value = 'curved-rod'
    shape.dispatchEvent(new Event('change'))
  }
  it('shows the automatic order and submits an editable order with planar settings', async () => {
    const { api } = setup({ currentDesign: { nanoparticles: particles } })
    await flush()
    chooseCurve()
    expect(button('Generate in current loadout').disabled).toBe(true)
    expect(document.querySelector('[aria-label="Platform rotation within fitted plane (degrees)"]').disabled).toBe(true)
    api.planGeneratedDesign.mockResolvedValue({ ...plan, shape: 'curved-rod', selected: { ...plan.selected, path_feature: 'sweep' }, path_particle_ids: ['np-0', 'np-2', 'np-1', 'np-3'], path_length_nm: 104 })
    button('Calculate design').click()
    await flush()
    expect(api.planGeneratedDesign).toHaveBeenLastCalledWith({ shape: 'curved-rod', pathing: 'colocalized', roll_deg: 0, duplex_bp: 18, extend_rod: true })
    const order = document.querySelector('[aria-label="Particle visit order"]')
    expect(order.value).toBe('1, 3, 2, 4')
    expect(document.querySelector('[role="status"]').textContent).toContain('Path feature: Sweep')
    expect(document.querySelector('[role="status"]').title).toContain('Planar path: 104.0 nm')
    // A displayed automatic order must not constrain subsequent searches.
    button('Calculate design').click()
    await flush()
    expect(api.planGeneratedDesign.mock.calls.at(-1)[0].particle_order).toBeUndefined()
    button('Generate in current loadout').click()
    await flush()
    expect(api.generateDesign).toHaveBeenLastCalledWith({ shape: 'curved-rod', pathing: 'colocalized', particle_order: ['np-0', 'np-2', 'np-1', 'np-3'], roll_deg: 0, duplex_bp: 18, extend_rod: true }, 17, 'part-a', expect.any(Function))
  })
  it('rejects repeated particle numbers and invalidates a reviewed path after reordering', async () => {
    const { api } = setup({ currentDesign: { nanoparticles: particles } })
    await flush()
    chooseCurve()
    const order = document.querySelector('[aria-label="Particle visit order"]')
    order.value = '1, 1, 3, 4'
    order.dispatchEvent(new Event('input'))
    button('Calculate design').click()
    await flush()
    expect(api.planGeneratedDesign).toHaveBeenCalledTimes(1)
    expect(document.body.textContent).toContain('exactly once')
    order.value = '4, 3, 2, 1'
    order.dispatchEvent(new Event('input'))
    button('Calculate design').click()
    await flush()
    expect(api.planGeneratedDesign).toHaveBeenLastCalledWith({ shape: 'curved-rod', pathing: 'colocalized', particle_order: ['np-3', 'np-2', 'np-1', 'np-0'], roll_deg: 0, duplex_bp: 18, extend_rod: true })
    order.dispatchEvent(new Event('input'))
    expect(button('Generate in current loadout').disabled).toBe(true)
  })
})


it('uses standard controls, exposes pathing, and moves explanatory text into tooltips', async () => {
  const { api } = setup({ currentDesign: { nanoparticles: Array.from({ length: 4 }, (_, i) => ({ id: String(i), kind: 'gold_nanosphere' })) } })
  await flush()
  const shape = document.querySelector('[aria-label="Design shape"]')
  expect(shape.classList.contains('select')).toBe(true)
  shape.value = 'curved-rod'
  shape.dispatchEvent(new Event('change'))
  const pathing = document.querySelector('[aria-label="Pathing"]')
  expect([...pathing.options].map(o => o.textContent)).toEqual(['Colocalized', 'Interior', 'Exterior'])
  expect(pathing.title).toContain('equators')
  pathing.value = 'interior'
  pathing.dispatchEvent(new Event('change'))
  expect(button('Generate in current loadout').disabled).toBe(true)
  button('Calculate design').click()
  await flush()
  expect(api.planGeneratedDesign).toHaveBeenLastCalledWith({ shape: 'curved-rod', pathing: 'interior', roll_deg: 0, duplex_bp: 18, extend_rod: true })
  expect(document.querySelectorAll('.modal__body p')).toHaveLength(0)
  expect([...document.querySelectorAll('.modal__body input')].every(i => i.classList.contains('input'))).toBe(true)
  expect(document.body.textContent).not.toContain('RMSF')
  expect(document.querySelector('[title*="uncalibrated"]')).not.toBeNull()
})

it('shows actual subprocess progress and retains error details without claiming completion', async () => {
  const { api, modal } = setup()
  await flush()
  let finish
  api.generateDesign.mockImplementation((settings, revision, doc, update) => {
    update({ stage: 'Route staple crossovers', detail: 'Pass 2; 48 crossovers placed', fraction: .37, steps: ['Create bundle', 'Route scaffold'] })
    return new Promise(resolve => { finish = resolve })
  })
  button('Generate in current loadout').click()
  expect(document.querySelector('progress').value).toBe(.37)
  expect(document.body.textContent).toContain('Pass 2; 48 crossovers placed')
  expect(document.body.textContent).toContain('✓ Create bundle')
  expect(button('Calculate design').disabled).toBe(true)
  modal.close()
  expect(modal.isOpen()).toBe(true)
  finish(null)
  await flush()
  expect(document.body.textContent).toContain('Generation failed')
  expect(document.body.textContent).toContain('Centers are unreachable')
  expect(document.querySelector('progress').value).toBe(.37)
  modal.close()
})

it('exposes independent mechanics levels and sends the reviewed choice', async () => {
  const { api, modal } = setup({ currentDesign: { nanoparticles: Array.from({ length: 4 }, (_,i) => ({ id: String(i), kind: 'gold_nanosphere' })) } })
  await flush()
  const shape = document.querySelector('[aria-label="Design shape"]')
  shape.value = 'curved-rod'; shape.dispatchEvent(new Event('change'))
  const mechanics = document.querySelector('[aria-label="Mechanical optimization"]')
  expect([...mechanics.options].map(x => x.value)).toEqual(['legacy','beam','variable','robust','fem-linear','fem-nonlinear','oxdna'])
  expect(mechanics.closest('label').parentElement.hidden).toBe(false)
  mechanics.value = 'fem-linear'; mechanics.dispatchEvent(new Event('change'))
  expect(button('Generate in current loadout').disabled).toBe(true)
  button('Calculate design').click(); await flush()
  expect(api.planGeneratedDesign.mock.lastCall[0].mechanics).toBe('fem-linear')
  api.generateDesign.mockResolvedValue({ generation: { connections: [], validation_job: { engine: 'cando', job_id: 'test-job', status: 'queued', qualification: 'Not calibrated.' } } })
  button('Generate in current loadout').click(); await flush()
  expect(api.generateDesign.mock.lastCall[0].mechanics).toBe('fem-linear')
  expect(document.body.textContent).toContain('test-job: queued')
  expect(document.body.textContent).toContain('Not calibrated')
  modal.close()
})

it('offers branched layouts below curved rods and submits only branch settings', async () => {
  const { api } = setup({ currentDesign: { nanoparticles: Array.from({ length: 4 }, (_, i) => ({ id: String(i), kind: 'gold_nanosphere' })) } })
  await flush()
  const shape = document.querySelector('[aria-label="Design shape"]')
  expect([...shape.options].map(o => o.value)).toEqual(['auto', 'curved-rod', 'branched'])
  shape.value = 'branched'; shape.dispatchEvent(new Event('change'))
  expect(button('Generate in current loadout').disabled).toBe(true)
  expect(document.body.textContent).toContain('Size curved arms, stems and junctions')
  api.planGeneratedDesign.mockResolvedValue({ ...plan, selected: { scaffold_size: 7249, scaffold_used_nt: 6300 }, qualification: 'Experimental planar lattice branches.' })
  button('Calculate design').click(); await flush()
  expect(api.planGeneratedDesign).toHaveBeenLastCalledWith({ shape: 'branched', branch_geometry: 'curved', branch_sizing: 'optimized', branch_scaffold_size: 'auto', roll_deg: 0, duplex_bp: 18, extend_rod: false })
  expect(document.querySelector('[role="status"]').textContent).toContain('6300 / 7249 scaffold bases')
  button('Generate in current loadout').click(); await flush()
  expect(api.generateDesign).toHaveBeenLastCalledWith({ shape: 'branched', branch_geometry: 'curved', branch_sizing: 'optimized', branch_scaffold_size: 'auto', roll_deg: 0, duplex_bp: 18, extend_rod: false }, 17, 'part-a', expect.any(Function))
})

it('retains straight lattice branches and invalidates the plan when branch geometry changes', async () => {
  const { api } = setup({ currentDesign: { nanoparticles: Array.from({ length: 4 }, (_, i) => ({ id: String(i), kind: 'gold_nanosphere' })) } })
  await flush()
  const shape = document.querySelector('[aria-label="Design shape"]')
  shape.value = 'branched'; shape.dispatchEvent(new Event('change'))
  const geometry = document.querySelector('[aria-label="Branch geometry"]')
  expect(geometry.value).toBe('curved')
  geometry.value = 'lattice'; geometry.dispatchEvent(new Event('change'))
  expect(button('Generate in current loadout').disabled).toBe(true)
  button('Calculate design').click(); await flush()
  expect(api.planGeneratedDesign.mock.lastCall[0].branch_geometry).toBe('lattice')
  expect(document.body.textContent).toContain('crosslinked straight branches')
})

it('selects scaffold budget and invalidates a reviewed branch plan', async () => {
  const { api } = setup({ currentDesign: { nanoparticles: Array.from({ length: 4 }, (_, i) => ({ id: String(i), kind: 'gold_nanosphere' })) } })
  await flush()
  const shape = document.querySelector('[aria-label="Design shape"]')
  shape.value = 'branched'; shape.dispatchEvent(new Event('change'))
  const scaffold = document.querySelector('[aria-label="Branch scaffold"]')
  expect(scaffold.value).toBe('auto')
  expect(scaffold.closest('label').parentElement.hidden).toBe(false)
  scaffold.value = '7249'; scaffold.dispatchEvent(new Event('change'))
  expect(button('Generate in current loadout').disabled).toBe(true)
  button('Calculate design').click(); await flush()
  expect(api.planGeneratedDesign.mock.lastCall[0].branch_scaffold_size).toBe(7249)
  const sizing = document.querySelector('[aria-label="Branch sizing"]')
  sizing.value = 'fixed'; sizing.dispatchEvent(new Event('change'))
  expect(scaffold.closest('label').parentElement.hidden).toBe(true)
  expect(button('Generate in current loadout').disabled).toBe(true)
  button('Calculate design').click(); await flush()
  expect(api.planGeneratedDesign.mock.lastCall[0].branch_sizing).toBe('fixed')
})

it('passes the reviewed connectivity tree through planning and generation with explicit assumed attachments', async () => {
  const connectivityPlan={nodes:[],edges:[],uniform_hb:6}
  const api={
    planGeneratedDesign:vi.fn(async()=>({...plan,selected:{scaffold_size:7249,scaffold_used_nt:2144,unused_scaffold_nt:5105},qualification:'Blunt-end attachments are assumed.'})),
    generateDesign:vi.fn(async()=>({generation:{connections:[],attachment_mode:'blunt-end-assumed',blunt_end_ports:[{},{},{},{}]}})),
  }
  const store={getState:()=>({currentDesign:{nanoparticles:Array.from({length:4},()=>({kind:'gold_nanosphere'}))}})}
  showGenerateDesign({api,store,connectivityPlan});await flush()
  expect(api.planGeneratedDesign.mock.lastCall[0].connectivity_plan).toEqual(connectivityPlan)
  button('Generate in current loadout').click();await flush()
  expect(api.generateDesign.mock.lastCall[0].connectivity_plan).toEqual(connectivityPlan)
  expect(document.body.textContent).toContain('4 blunt-end attachment faces')
  expect(document.body.textContent).toContain('Overhangs and NP binding remain unassigned')
})
