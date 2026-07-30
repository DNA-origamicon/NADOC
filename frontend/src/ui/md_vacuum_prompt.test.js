import { describe, it, expect, afterEach } from 'vitest'
import {
  VACUUM_CANCEL,
  VACUUM_MIN_HELICES,
  VACUUM_RUN,
  VACUUM_SKIP,
  needsVacuumPrompt,
  openVacuumPromptModal,
  vacuumPromptMessage,
} from './md_vacuum_prompt.js'

describe('needsVacuumPrompt', () => {
  it('asks only below the threshold', () => {
    expect(needsVacuumPrompt(1)).toBe(true)
    expect(needsVacuumPrompt(2)).toBe(true)
    expect(needsVacuumPrompt(3)).toBe(true)
    expect(needsVacuumPrompt(VACUUM_MIN_HELICES)).toBe(false)
    expect(needsVacuumPrompt(6)).toBe(false)
    expect(needsVacuumPrompt(24)).toBe(false)
  })

  it('never asks when the helix count is unknown or nonsensical', () => {
    expect(needsVacuumPrompt(0)).toBe(false)
    expect(needsVacuumPrompt(undefined)).toBe(false)
    expect(needsVacuumPrompt(null)).toBe(false)
    expect(needsVacuumPrompt(NaN)).toBe(false)
  })
})

describe('vacuumPromptMessage', () => {
  it('is null when no prompt is needed', () => {
    expect(vacuumPromptMessage(6)).toBeNull()
  })

  it('names the actual helix count and explains the measured cost', () => {
    const msg = vacuumPromptMessage(2)
    expect(msg.title).toMatch(/skip/i)
    expect(msg.lines.join(' ')).toContain('2 helices')
    expect(msg.lines.join(' ')).toContain('6.8%')
  })

  it('uses the singular for a one-helix design', () => {
    expect(vacuumPromptMessage(1).lines.join(' ')).toContain('1 helix')
  })
})

describe('openVacuumPromptModal (DOM)', () => {
  afterEach(() => { document.body.innerHTML = '' })

  const modal = () => document.querySelector('[data-testid="vacuum-prestage-modal"]')
  const btn = (choice) =>
    document.querySelector(`[data-testid="vacuum-prestage-modal"] button[data-choice="${choice}"]`)

  it('does not open for a design that needs no prompt', async () => {
    await expect(openVacuumPromptModal(6)).resolves.toBe(VACUUM_RUN)
    expect(modal()).toBeNull()
  })

  it('offers both answers and resolves SKIP', async () => {
    const p = openVacuumPromptModal(2)
    expect(modal()).toBeTruthy()
    expect(modal().dataset.helices).toBe('2')
    expect(btn('skip')).toBeTruthy()
    expect(btn('run')).toBeTruthy()
    btn('skip').click()
    await expect(p).resolves.toBe(VACUUM_SKIP)
    expect(modal()).toBeNull()
  })

  it('resolves RUN when the user keeps the step', async () => {
    const p = openVacuumPromptModal(3)
    btn('run').click()
    await expect(p).resolves.toBe(VACUUM_RUN)
  })

  it('dismissing CANCELS rather than silently choosing', async () => {
    const p = openVacuumPromptModal(2)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(p).resolves.toBe(VACUUM_CANCEL)
  })
})
