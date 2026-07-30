import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  initRelaxPresets, pickInitial, noteFor, applyDefaultsTo, presetIdForProtocol,
  PRESET_FALLBACK,
} from './md_relax_presets.js'

const CATALOGUE = {
  default: 'standard',
  presets: [
    { id: 'fast_shape', label: 'Fast Shape Check (Vacuum)', summary: 'No solvent.',
      available: false, unavailable_reason: 'Needs the vacuum ENRG-MD pipeline.',
      reference: 'tutorial step 2', defaults: { water_shell_nm: 0 },
      protocol: 'equilibrium_aware_namd', is_default: false },
    { id: 'implicit_gbis', label: 'Implicit Solvent (GBIS)', summary: 'Continuum solvent.',
      available: true, unavailable_reason: '', reference: 'NAMD GBIS',
      defaults: { protocol: 'implicit_gbis_namd' },
      protocol: 'implicit_gbis_namd', is_default: false },
    { id: 'standard', label: 'Standard (Aksimentiev)', summary: 'Explicit MgCl2.',
      available: true, unavailable_reason: '', reference: 'MMB 1811 (2018)',
      defaults: { padding_nm: 1.2, early_stop_relax: true },
      protocol: 'equilibrium_aware_namd', is_default: true },
    { id: 'full_physics', label: 'Slow (full physics)', summary: 'Solvent-first.',
      available: true, unavailable_reason: '', reference: 'ACS Nano 13 (2019)',
      defaults: { padding_nm: 1.5, early_stop_relax: false },
      protocol: 'equilibrium_aware_namd', is_default: false },
  ],
}

describe('pickInitial', () => {
  it('starts on the catalogue default', () => {
    expect(pickInitial(CATALOGUE)).toBe('standard')
  })
  it('honours a preferred id when it is available', () => {
    expect(pickInitial(CATALOGUE, 'full_physics')).toBe('full_physics')
  })
  it('refuses to start on an unavailable preset', () => {
    expect(pickInitial(CATALOGUE, 'fast_shape')).toBe('standard')
  })
  it('survives an empty catalogue', () => {
    expect(pickInitial({ presets: [] })).toBe(null)
  })
})

describe('noteFor', () => {
  it('shows summary plus reference for an available preset', () => {
    expect(noteFor(CATALOGUE.presets[2])).toBe('Explicit MgCl2. — MMB 1811 (2018)')
  })
  it('leads with the reason for an unavailable one', () => {
    expect(noteFor(CATALOGUE.presets[0]))
      .toBe('Not available in this build. Needs the vacuum ENRG-MD pipeline.')
  })
  it('is empty for no preset', () => {
    expect(noteFor(null)).toBe('')
  })
})

describe('applyDefaultsTo', () => {
  it('fills untouched fields', () => {
    const out = applyDefaultsTo(CATALOGUE.presets[3], { mg_conc_mM: 12.5 }, new Set())
    expect(out).toEqual({ mg_conc_mM: 12.5, padding_nm: 1.5, early_stop_relax: false })
  })
  it('never overwrites a field the user touched', () => {
    const out = applyDefaultsTo(CATALOGUE.presets[3],
      { padding_nm: 3.0, early_stop_relax: true }, new Set(['padding_nm', 'early_stop_relax']))
    expect(out.padding_nm).toBe(3.0)
    expect(out.early_stop_relax).toBe(true)
  })
  it('does not mutate the input', () => {
    const cur = { padding_nm: 9 }
    applyDefaultsTo(CATALOGUE.presets[2], cur, new Set())
    expect(cur).toEqual({ padding_nm: 9 })
  })
})

describe('initRelaxPresets', () => {
  let selectEl, noteEl

  beforeEach(() => {
    document.body.innerHTML = '<select id="s"></select><div id="n"></div>'
    selectEl = document.getElementById('s')
    noteEl = document.getElementById('n')
  })

  it('renders every preset, disabling the unavailable one', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    const opts = [...selectEl.options]
    expect(opts.map(o => o.value))
      .toEqual(['fast_shape', 'implicit_gbis', 'standard', 'full_physics'])
    expect(opts[0].disabled).toBe(true)
    expect(opts[0].textContent).toContain('unavailable')
    expect(opts[2].disabled).toBe(false)
    expect(ui.id()).toBe('standard')
  })

  it('defaults to Standard and shows its note', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    expect(selectEl.value).toBe('standard')
    expect(noteEl.textContent).toContain('Explicit MgCl2')
  })

  it('updates the note and fires onChange on selection', async () => {
    const onChange = vi.fn()
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE, onChange })
    await ui.load()
    selectEl.value = 'full_physics'
    selectEl.dispatchEvent(new Event('change'))
    expect(ui.id()).toBe('full_physics')
    expect(noteEl.textContent).toContain('Solvent-first')
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'full_physics' }))
  })

  it('rejects a scripted selection of an unavailable preset', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    selectEl.value = 'fast_shape'
    selectEl.dispatchEvent(new Event('change'))
    expect(ui.id()).toBe('standard')
    expect(selectEl.value).toBe('standard')
  })

  it('falls back to a usable menu when the backend is unreachable', async () => {
    const ui = initRelaxPresets({
      selectEl, noteEl, fetchPresets: async () => { throw new Error('offline') },
    })
    await ui.load()
    expect(ui.id()).toBe(PRESET_FALLBACK.default)
    expect(selectEl.options.length).toBe(1)
  })

  it('applies the current preset defaults under touched fields', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load('full_physics')
    expect(ui.applyDefaultsTo({ padding_nm: 2.5 }, new Set(['padding_nm'])).padding_nm).toBe(2.5)
    expect(ui.applyDefaultsTo({}, new Set()).padding_nm).toBe(1.5)
  })
})


describe('derived protocol (the merge)', () => {
  let selectEl, noteEl
  beforeEach(() => {
    document.body.innerHTML = '<select id="s"></select><div id="n"></div>'
    selectEl = document.getElementById('s'); noteEl = document.getElementById('n')
  })

  it('reports the protocol of whichever preset is selected', async () => {
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    expect(ui.protocol()).toBe('equilibrium_aware_namd')
    selectEl.value = 'implicit_gbis'
    selectEl.dispatchEvent(new Event('change'))
    expect(ui.protocol()).toBe('implicit_gbis_namd')
  })

  it('has no way to express a preset/protocol contradiction', async () => {
    // the whole point of the merge: protocol is a function of the preset, not a
    // second control that can disagree with it
    const ui = initRelaxPresets({ selectEl, noteEl, fetchPresets: async () => CATALOGUE })
    await ui.load()
    for (const p of CATALOGUE.presets) {
      selectEl.value = p.id
      selectEl.dispatchEvent(new Event('change'))
      if (p.available) expect(ui.protocol()).toBe(p.protocol)
    }
  })

  it('falls back to the explicit protocol when nothing is loaded', () => {
    const ui = initRelaxPresets({ selectEl: null, noteEl: null, fetchPresets: async () => ({}) })
    expect(ui.protocol()).toBe('equilibrium_aware_namd')
  })
})

describe('presetIdForProtocol', () => {
  it('maps a protocol back to the preset that runs it', () => {
    expect(presetIdForProtocol(CATALOGUE, 'implicit_gbis_namd')).toBe('implicit_gbis')
  })
  it('prefers an AVAILABLE preset', () => {
    // fast_shape also claims equilibrium_aware_namd but is unavailable
    expect(presetIdForProtocol(CATALOGUE, 'equilibrium_aware_namd')).toBe('standard')
  })
  it('returns null for the retired legacy protocol', () => {
    expect(presetIdForProtocol(CATALOGUE, 'mgh_slow_release')).toBe(null)
  })
})
