// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { chooseAutostapleMethod, chooseExperimentalAutostaple, showExperimentalAutostapleReport } from './autostaple_options.js'
import { runAutostapleCommand } from './region_autostaple.js'
const button = label => [...document.querySelectorAll('button')].find(n => n.textContent === label)
const input = label => document.querySelector(`[aria-label="${label}"]`)
it('shows cluster folding order and keeps default routing unchanged', async () => {
  const pending = chooseExperimentalAutostaple({ design: { lattice_type: 'HONEYCOMB', cluster_transforms: [
    { id: 'a', name: 'Cluster 1' }, { id: 'b', name: 'Cluster 2', folding_order: 1 },
    { id: 'c', name: 'Cluster 3', folding_order: 2 },
  ] } })
  expect(document.body.textContent).toContain('Stage 1: Cluster 2 → Stage 2: Cluster 3')
  expect(document.body.textContent).toContain('Undefined — default routing: Cluster 1')
  const routing = input('Folding-order routing')
  routing.value = 'ordered'; routing.dispatchEvent(new Event('change'))
  expect(button('Apply').disabled).toBe(false)
  routing.value = 'default'; routing.dispatchEvent(new Event('change'))
  expect(button('Apply').disabled).toBe(false)
  button('Apply').click()
  expect(await pending).not.toHaveProperty('folding_order')
})
it('submits folding order and validates the temperature gap', async () => {
  const pending = chooseExperimentalAutostaple({ design: { lattice_type: 'HONEYCOMB',
    cluster_transforms: [{ folding_order: 1 }, { folding_order: 2 }] } })
  input('Folding-order routing').value = 'ordered'
  input('Folding-order routing').dispatchEvent(new Event('change'))
  input('Temperature gap').value = '0'
  button('Apply').click()
  expect(document.querySelector('[role="alert"]').textContent).toContain('temperature gap')
  input('Temperature gap').value = '3.5'
  button('Apply').click()
  expect(await pending).toMatchObject({ folding_order: true, temperature_gap_c: 3.5 })
})
it('blocks ordering for regional requests and missing stages', async () => {
  for (const regional of [true, false]) {
    const pending = chooseExperimentalAutostaple({ regional, design: { lattice_type: 'HONEYCOMB' } })
    input('Folding-order routing').value = 'ordered'
    input('Folding-order routing').dispatchEvent(new Event('change'))
    expect(button('Apply').disabled).toBe(true)
    button('Cancel').click()
    expect(await pending).toBeNull()
  }
})
it('reports achieved cluster temperatures and actual nick choices', () => {
  showExperimentalAutostapleReport({ crossover_repeat_bp: 42, pattern: 0, folding_result: {
    gap_c: 2, default_routed_staples: 4,
    clusters: [{ stage: 1, name: 'Early', median_c: 64.1, min_c: 60, max_c: 68, count: 5 }],
    stages: [{ stage: 1, crossover_repeat_bp: 42, length_cap_nt: null, added_nicks: 0 }],
  } })
  expect(document.body.textContent).toContain('median 64.1 °C')
  expect(document.body.textContent).toContain('4 staples outside the temperature objective')
  expect(document.body.textContent).toContain('42 bp repeats')
  expect(document.body.textContent).toContain('baseline lengths')
})
afterEach(() => { button('Cancel')?.click(); button('Close')?.click(); document.body.innerHTML = '' })

it('defaults to Standard, accepts Experimental, and cancels without running', async () => {
  let pending = chooseAutostapleMethod()
  expect(input('Method').value).toBe('standard')
  expect(input('Maximum staple length')).toBeNull()
  input('Method').value = 'experimental'; button('OK').click()
  expect(await pending).toBe('experimental')
  pending = chooseAutostapleMethod(); button('Cancel').click()
  expect(await pending).toBeNull()
})
it('shows 42 bp options only in Experimental, validates and submits chosen values', async () => {
  const pending = chooseExperimentalAutostaple({ design: { lattice_type: 'HONEYCOMB' }, regional: true })
  expect(document.body.textContent).toContain('every touching staple')
  expect(input('HC crossover repeat').value).toBe('42')
  input('Minimum staple length').value = '80'; button('Apply').click()
  expect(document.querySelector('[role="alert"]').textContent).toContain('minimum')
  input('Staple merge limit').value = '84'; input('Pattern').value = '1'; button('Apply').click()
  expect(await pending).toEqual({ crossover_repeat_bp: 42, pattern: 1, min_length: 80, max_merged_length: 84, max_staple_length: 60 })
})
it('rejects empty inputs and disables unsupported lattices', async () => {
  let pending = chooseExperimentalAutostaple({ design: { lattice_type: 'HONEYCOMB' } })
  input('Minimum staple length').value = ''; button('Apply').click()
  expect(document.querySelector('[role="alert"]').textContent).toBeTruthy()
  button('Cancel').click(); expect(await pending).toBeNull()
  pending = chooseExperimentalAutostaple({ design: { lattice_type: 'SQUARE' } })
  expect(button('Apply').disabled).toBe(true)
  button('Cancel').click(); expect(await pending).toBeNull()
})
it('passes experimental options and scope together, and displays realized results', async () => {
  const experimental = { crossover_repeat_bp: 42, pattern: 0, min_length: 21, max_merged_length: 84 }
  const report = { ...experimental, staple_lengths: { 42: 5 }, domain_lengths: { 28: 3 } }
  const deps = { design: { helices: [{}] }, region: [{ helix_id: 'h', lo_bp: 0, hi_bp: 10 }],
    chooseMethod: async () => 'experimental', choose: async () => 'region', chooseExperimental: async () => experimental,
    autostaple: vi.fn(async () => ({ full_autostaple: { experimental: report } })),
    showProgress: vi.fn(), hideProgress: vi.fn(), toast: vi.fn() }
  await runAutostapleCommand(deps)
  expect(deps.autostaple).toHaveBeenCalledWith({ scaffold_name: 'M13mp18', region: deps.region, experimental })
  expect(document.body.textContent).toContain('42 nt: 5')
  button('Close').click()
  deps.autostaple.mockClear(); deps.chooseExperimental = async () => null
  await runAutostapleCommand(deps)
  expect(deps.autostaple).not.toHaveBeenCalled()
  deps.chooseMethod = async () => null
  await runAutostapleCommand(deps)
  expect(deps.autostaple).not.toHaveBeenCalled()
})
it('reports empty scope distributions', () => {
  showExperimentalAutostapleReport({ crossover_repeat_bp: 42, pattern: 1 })
  expect(document.body.textContent).toContain('pattern B')
  expect(document.body.textContent).toContain('No staples')
})

it('validates the hard maximum inside Experimental and sends the user value', async () => {
  const pending = chooseExperimentalAutostaple({ design: { lattice_type: 'HONEYCOMB' } })
  input('Maximum staple length').value = '20'; button('Apply').click()
  expect(document.querySelector('[role="alert"]').textContent).toContain('21 and 300')
  input('Maximum staple length').value = '80'; button('Apply').click()
  const settings = await pending
  const autostaple = vi.fn(async () => ({}))
  await runAutostapleCommand({ design: { helices: [{}] }, chooseMethod: async () => 'experimental',
    chooseExperimental: async () => settings, autostaple, showProgress: vi.fn(), hideProgress: vi.fn(), toast: vi.fn() })
  expect(autostaple).toHaveBeenCalledWith({ scaffold_name: 'M13mp18', max_staple_length: 80,
    experimental: { crossover_repeat_bp: 42, pattern: 0, min_length: 21, max_merged_length: 56 } })
})
it('keeps the Standard request unchanged and never opens Experimental settings', async () => {
  const pending = chooseAutostapleMethod()
  expect(input('Maximum staple length')).toBeNull()
  button('OK').click()
  const method = await pending
  const autostaple = vi.fn(async () => ({}))
  const chooseExperimental = vi.fn()
  await runAutostapleCommand({ design: { helices: [{}] }, chooseMethod: async () => method,
    chooseExperimental, autostaple, showProgress: vi.fn(), hideProgress: vi.fn(), toast: vi.fn() })
  expect(chooseExperimental).not.toHaveBeenCalled()
  expect(autostaple).toHaveBeenCalledWith({ scaffold_name: 'M13mp18' })
})
