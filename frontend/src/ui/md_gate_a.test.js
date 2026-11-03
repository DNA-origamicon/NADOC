import { describe, it, expect, afterEach } from 'vitest'
import { gateAMessage, openGateAModal } from './md_gate_a.js'

const A3 = {
  skipped: false,
  tier: 'a3',
  vram_mb: 12_288,
  current_atoms: 9_000_000,
  current_vram_mb: 34_000,
}

describe('gateAMessage', () => {
  it('labels the atom upper budget and separates preparation memory', () => {
    const message = gateAMessage({...A3,atom_estimate_kind:'upper_bound',preparation_ram_mb:6144})
    expect(message.lines.join(' ')).toContain('budgeted for up to 9,000,000 atoms')
    expect(message.lines.join(' ')).toContain('Preparation budget: 6.0 GB host RAM')
    expect(message.canProceed).toBe(false)
  })
  it('blocks unknown budgets and insufficient reserved headroom', () => {
    expect(gateAMessage({tier:'unknown',reason:'Missing memory reading'}).canProceed).toBe(false)
    expect(gateAMessage({tier:'headroom',require_reserved_budget:true,
      current_atoms:1000000,current_vram_mb:4000,vram_budget_mb:3500}).canProceed).toBe(false)
  })

  it('shows the explicit lower-memory execution alternative', () => {
    const message = gateAMessage({...A3,execution_modes:{offload:{supported:true,
      ram_mib:6000,health_ram_mib:2000,gpu_mib:5000}}})
    expect(message.lines.join(' ')).toMatch(/CUDA offload estimate/)
    expect(message.lines.join(' ')).toMatch(/health analysis/)
  })
  it('allows a fitting estimate and blocks skipped or missing sizing', () => {
    expect(gateAMessage({ tier: 'ok' })).toBeNull()
    expect(gateAMessage({ skipped: true, tier: 'ok' }).canProceed).toBe(false)
    expect(gateAMessage(null).canProceed).toBe(false)
  })

  it('hard-stops a fully solvated system that does not fit', () => {
    const m = gateAMessage(A3)
    expect(m.canProceed).toBe(false)
    expect(m.title).toMatch(/fully solvated system does not fit/i)
    expect(m.lines.join(' ')).toMatch(/33\.2 GB/)
    expect(m.lines.join(' ')).toMatch(/Alpine, or RunPod/i)
  })
})

describe('openGateAModal', () => {
  afterEach(() => { document.body.innerHTML = '' })
  const modal = () => document.querySelector('[data-testid="gate-a-modal"]')
  const btn = (choice) => document.querySelector(
    `[data-testid="gate-a-modal"] button[data-choice="${choice}"]`,
  )

  it('lets a fitting estimate pass without a modal', async () => {
    await expect(openGateAModal({ tier: 'ok' })).resolves.toBe(true)
    expect(modal()).toBeNull()
  })

  it('shows only Close for an oversized full box', async () => {
    const p = openGateAModal(A3)
    expect(modal().dataset.tier).toBe('a3')
    expect(btn('proceed')).toBeNull()
    expect(btn('cancel').textContent).toBe('Close')
    btn('cancel').click()
    await expect(p).resolves.toBe(false)
  })

  it('Escape resolves false', async () => {
    const p = openGateAModal(A3)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(p).resolves.toBe(false)
    expect(modal()).toBeNull()
  })
})

const HOST_HEADROOM = {
  tier: 'headroom', bound: 'host RAM', current_atoms: 3156200,
  current_vram_mb: 10415, vram_mb: 12288, vram_budget_mb: 10444,
  current_host_mb: 7891, host_mb: 12473, host_budget_mb: 7483,
}

it('explains host RAM headroom when the GPU fits and permits continuing',async()=>{
  const message=gateAMessage(HOST_HEADROOM)
  expect(message.canProceed).toBe(true)
  expect(message.title).toContain('Host RAM')
  expect(message.lines.join(' ')).toContain('GPU capacity: 12.0 GB')
  expect(message.lines.join(' ')).toContain('currently available host RAM: 12.2 GB')
  expect(message.lines.join(' ')).toContain('recommended 7.31 GB budget')
  const decision=openGateAModal(HOST_HEADROOM)
  document.querySelector('[data-choice="proceed"]').click()
  await expect(decision).resolves.toBe(true)
})

it('allows cancelling a headroom warning',async()=>{
  const decision=openGateAModal(HOST_HEADROOM)
  document.querySelector('[data-choice="cancel"]').click()
  await expect(decision).resolves.toBe(false)
})

it('identifies an actual host shortage instead of falsely blaming GPU memory',()=>{
  const message=gateAMessage({...HOST_HEADROOM,tier:'a3',host_mb:7000})
  expect(message.canProceed).toBe(false)
  expect(message.lines.join(' ')).toContain('Host RAM is the limiting resource')
  expect(message.lines.join(' ')).not.toContain('Select a GPU')
})

it('explains GPU reserve separately from installed capacity',()=>{
  const message=gateAMessage({...HOST_HEADROOM,bound:'GPU',current_vram_mb:11550,host_mb:30000})
  expect(message.canProceed).toBe(true)
  expect(message.title).toContain('GPU memory')
  expect(message.lines.join(' ')).toContain('recommended 10.20 GB budget')
})
