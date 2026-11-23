// @vitest-environment jsdom
import { it, expect, afterEach } from 'vitest'
import { resourceChoiceReason, solverResourceWizard } from './solver_resource_wizard.js'
afterEach(() => document.body.replaceChildren())
const need = { ram_gib: 40, vram_gib: 20, disk_gib: 3, min_ram_gib: 50, min_vram_gb: 26 }
const small = { id: 'small', vram_gb: 24, on_demand: .5 }
const big = { id: 'big', vram_gb: 48, on_demand: 1 }
const initial = { python: '/env/bin/python', arbd: '/bin/arbd', mem_gb: 32, cores: 8 }
const button = name => [...document.querySelectorAll('button')].find(b => b.textContent === name)
it('rejects unknown GPU capacity, CPU mrDNA and insufficient host RAM', () => {
  expect(resourceChoiceReason({}, need, 'runpod', 'mrdna')).toContain('unknown VRAM')
  expect(resourceChoiceReason({ cuda: false }, need, 'alpine', 'mrdna')).toContain('CUDA')
  expect(resourceChoiceReason({ cuda: true, vram_gb: 48, max_ram_gib: 49 }, need, 'alpine', 'mrdna')).toContain('RAM')
  expect(resourceChoiceReason({ on_demand: 1 }, { min_ram_gib: 2, min_vram_gb: 0 }, 'runpod', 'snupi')).toBe('')
})
it('disables undersized GPUs and RAM, requires review, and returns the actual quote', async () => {
  const promise = solverResourceWizard({ engine: 'mrdna', target: 'runpod', need, rows: [small, big], initial })
  expect(document.querySelector('input[value="small"]').disabled).toBe(true)
  const ram = document.querySelector('[name="mem_gb"]')
  expect(ram.value).toBe('50')
  ram.value = '49'; ram.dispatchEvent(new Event('input', { bubbles: true }))
  expect(button('Review resources').disabled).toBe(true)
  ram.value = '50'; ram.dispatchEvent(new Event('input', { bubbles: true }))
  button('Review resources').click()
  expect(button('Rent pod and start')).toBeTruthy()
  button('Back').click(); button('Review resources').click(); button('Rent pod and start').click()
  expect(await promise).toMatchObject({ execution_target: 'runpod', runpod_settings: { gpu_id: 'big', quoted_rate: 1, mem_gb: 50 } })
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})
it('keeps no-fit selections blocked and resolves cancellation without an allocation', async () => {
  const promise = solverResourceWizard({ engine: 'mrdna', target: 'runpod', need, rows: [small], initial })
  expect(button('Review resources').disabled).toBe(true)
  expect(document.body.textContent).toContain('No available resource')
  button('Cancel').click(); expect(await promise).toBeNull()
})
it('couples Alpine RAM to CPU allocation and enforces QoS time limits', async () => {
  const row = { id: 'alpine', cuda: true, vram_gb: 48, max_cores: 64, mem_per_core_gb: 4, max_ram_gib: 256, qos: [{ name: 'gpu-normal', minutes: 60 }] }
  const promise = solverResourceWizard({ engine: 'mrdna', target: 'alpine', need, rows: [row], initial })
  expect(document.querySelector('[name="cores"]').value).toBe('13')
  const time = document.querySelector('[name="walltime_minutes"]')
  time.value = '61'; time.dispatchEvent(new Event('input', { bubbles: true }))
  expect(button('Review resources').disabled).toBe(true)
  time.value = '60'; time.dispatchEvent(new Event('input', { bubbles: true }))
  button('Review resources').click(); button('Submit job').click()
  expect(await promise).toMatchObject({ cluster_settings: { cores: 13, mem_gb: 50, qos: 'gpu-normal', walltime_minutes: 60 } })
})
it('closes and cancels when the owning panel is disposed', async () => {
  const controller = new AbortController()
  const promise = solverResourceWizard({ engine: 'mrdna', target: 'runpod', need, rows: [big], initial, signal: controller.signal })
  controller.abort()
  expect(await promise).toBeNull()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})

it('checks availability before review and submits only the reviewed allocation', async () => {
  let finish
  let checked
  const promise = solverResourceWizard({ engine: 'mrdna', target: 'runpod', need, rows: [big], initial,
    checkAllocation: settings => { checked = { ...settings }; return new Promise(resolve => { finish = resolve }) },
  })
  expect(document.querySelector('[name="mem_gb"]').className).toContain('input--data')
  expect(document.querySelector('[role=group]').getAttribute('aria-label')).toBe('RunPod GPUs')
  expect(button('Cancel').className).toContain('btn')
  expect(button('Back').className).toContain('btn')
  expect(button('Review resources').className).toContain('btn--primary')
  button('Review resources').click()
  expect(document.querySelector('form').inert).toBe(true)
  expect(button('Review resources').disabled).toBe(true)
  finish(); await Promise.resolve()
  expect(document.querySelector('form').inert).toBe(false)
  document.querySelector('[name="mem_gb"]').value = '100'
  button('Rent pod and start').click()
  expect((await promise).runpod_settings).toEqual(checked)
})

it('keeps unavailable allocations out of review and supports cancellation during checks', async () => {
  const promise = solverResourceWizard({ engine: 'snupi', target: 'runpod', need, rows: [big], initial,
    checkAllocation: async () => { throw new Error('No matching capacity') },
  })
  button('Review resources').click(); await Promise.resolve()
  expect(button('Rent pod and start')).toBeUndefined()
  expect(document.body.textContent).toContain('No matching capacity')
  button('Cancel').click(); expect(await promise).toBeNull()
  let finish
  const pending = solverResourceWizard({ engine: 'snupi', target: 'runpod', need, rows: [big], initial,
    checkAllocation: () => new Promise(resolve => { finish = resolve }),
  })
  button('Review resources').click(); button('Cancel').click()
  expect(await pending).toBeNull()
  finish(); await Promise.resolve()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})

it('refreshes stock for the edited allocation and blocks a selected GPU that became unavailable', async () => {
  let requested
  const promise = solverResourceWizard({ engine: 'mrdna', target: 'runpod', need, rows: [{ ...big, stock: 'High' }], initial,
    loadRows: async settings => { requested = settings; return [{ ...big, stock: 'None' }] },
  })
  document.querySelector('[name=mem_gb]').value = '100'
  button('Re-check availability').click(); await Promise.resolve()
  expect(requested).toEqual({ mem_gb: 100, cores: 8 })
  expect(document.querySelector('[value=big]').disabled).toBe(true)
  expect(button('Review resources').disabled).toBe(true)
  button('Cancel').click()
  expect(await promise).toBeNull()
})
