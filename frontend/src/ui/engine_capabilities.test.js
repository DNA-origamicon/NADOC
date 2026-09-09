/**
 * U1 PARITY-CENSUS oracle for the engine capability descriptor.
 *
 * The descriptor (engine_capabilities.js) is the single source of truth that will
 * drive ONE shared card stack instead of the 5 bespoke *_jobs_panel.js panels
 * (U2/U3/U4). This test proves a CAPABILITY, not "it renders": for every engine
 * the descriptor's ENABLED card set must equal EXACTLY the cards that engine's
 * bespoke panel renders in index.html today — no card omitted, none invented —
 * and every unsupported card must be PRESENT-BUT-DISABLED (with a why-reason),
 * never absent from the descriptor.
 *
 * Three independent anchors make this falsifiable (can-go-red):
 *   1. CENSUS — a hand-audited ground-truth matrix (from the 2026-07-08 panel
 *      inventory) that the descriptor must match field-for-field. Editing the
 *      descriptor to omit/invent a card diverges from the census → red.
 *   2. LIVE DOM (no invention) — every card the descriptor marks enabled has a
 *      domAnchorId that MUST exist in the real index.html.
 *   3. LIVE DOM (no silent support) — every card the descriptor marks unsupported
 *      has a conventional probe id that MUST NOT exist in index.html (if a panel
 *      grows that card, the descriptor must be updated or this goes red).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  ENGINE_KEYS, CARD_KEYS, ENGINE_LABELS, CARD_LABELS,
  ENGINE_CAPABILITIES, GLOBAL_CARDS,
  engineCards, supportsCard, cardReason, enabledCardKeys,
} from './engine_capabilities.js'

const HTML = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'index.html'),
  'utf8',
)
const idPresent = (id) => HTML.includes(`id="${id}"`)

// --- Independent ground-truth census (audited from the bespoke panels) --------
// enabled: card the panel renders today, with its verified DOM toggle/button id.
// disabled: card absent today, with the conventional id it WOULD use + why.
const CENSUS = {
  oxdna: {
    run:        { on: 'oxdna-jobs-run-btn' },
    efield:     { on: 'efield-toggle' },
    anchors:    { on: 'oxdna-anchors-toggle' },
    surface:    { on: 'oxdna-floor-toggle' },
    advanced:   { on: 'oxdna-jobs-adv-toggle' },
    viz:        { on: 'oxdna-jobs-viz-toggle' },
    metrics:    { on: 'oxdna-metrics-toggle' },
    joblist:    { on: 'oxdna-jobs-list-toggle' },
  },
  mrdna: {
    run:        { on: 'mrdna-jobs-coarse-btn' },
    efield:     { on: 'mrdna-efield-toggle' },
    anchors:    { on: 'mrdna-anchors-toggle' },
    surface:    { on: 'mrdna-surface-toggle' },
    advanced:   { on: 'mrdna-jobs-adv-toggle' },
    viz:        { on: 'mrdna-jobs-display-toggle' },
    metrics:    { off: 'mrdna-metrics-toggle' },
    joblist:    { on: 'mrdna-jobs-list-toggle' },
  },
  cando: {
    run:        { on: 'cando-jobs-coarse-btn' },
    efield:     { on: 'cando-efield-toggle' },
    anchors:    { on: 'cando-anchors-toggle' },
    surface:    { off: 'cando-surface-toggle' },
    advanced:   { on: 'cando-jobs-adv-toggle' },
    viz:        { on: 'cando-display-toggle' },
    metrics:    { on: 'cando-metrics-toggle' },
    joblist:    { on: 'cando-jobs-list-toggle' },
  },
  // ARCHIVED (2026-07-20): 'blade' is no longer in ENGINE_KEYS, so this census row is never
  // iterated. Kept for a one-line revive (re-add 'blade' to ENGINE_KEYS + the array below).
  blade: {
    run:        { on: 'blade-jobs-run-btn' },
    efield:     { off: 'blade-efield-toggle' },
    anchors:    { off: 'blade-anchors-toggle' },
    surface:    { off: 'blade-surface-toggle' },
    advanced:   { on: 'blade-jobs-adv-toggle' },
    viz:        { on: 'blade-display-toggle' },
    metrics:    { on: 'blade-metrics-toggle' },
    joblist:    { on: 'blade-jobs-list-toggle' },
  },
  snupi: {
    run:        { on: 'snupi-jobs-coarse-btn' },
    efield:     { on: 'snupi-efield-toggle' },
    anchors:    { on: 'snupi-anchors-toggle' },
    surface:    { off: 'snupi-surface-toggle' },
    advanced:   { on: 'snupi-jobs-adv-toggle' },
    viz:        { on: 'snupi-display-toggle' },
    metrics:    { on: 'snupi-metrics-toggle' },
    joblist:    { on: 'snupi-jobs-list-toggle' },
  },
  namd: {
    run:        { on: 'md-jobs-run-btn' },
    efield:     { on: 'md-efield-toggle' },
    anchors:    { on: 'md-anchors-toggle' },
    surface:    { on: 'md-surface-toggle' },
    advanced:   { on: 'md-jobs-new-btn' },   // the Job Wizard replaced the drawer
    viz:        { on: 'md-jobs-viz-toggle' },
    metrics:    { on: 'md-metrics-toggle' },
    joblist:    { on: 'md-jobs-list-toggle' },
  },
}

describe('engine capability descriptor — shape + completeness', () => {
  it('covers exactly the five selectable simulation engines, fast→accurate tab order', () => {
    // Tab order: CanDo (FEM) · SNUPI (FEM) · mrDNA · oxDNA · NAMD.
    // SNUPI is the same in-process FEM as CanDo, run with the anisotropic SNUPI material.
    // BLADE was ARCHIVED 2026-07-20 (removed from ENGINE_KEYS — its capability/census entries
    // stay dormant; see engine_capabilities.js). LAMMPS is deliberately NOT a selectable engine
    // — it's the auto-policy CPU fallback, shown in the unified job list with an [L] badge.
    expect(ENGINE_KEYS).toEqual(['cando', 'snupi', 'mrdna', 'oxdna', 'namd'])
  })

  it('every engine has an entry for EVERY card in the universe (never absent)', () => {
    for (const eng of ENGINE_KEYS) {
      const caps = ENGINE_CAPABILITIES[eng]
      expect(caps, `capabilities for ${eng}`).toBeTruthy()
      for (const card of CARD_KEYS) {
        expect(caps.cards[card], `${eng}.${card} entry present`).toBeTruthy()
        expect(typeof caps.cards[card].enabled).toBe('boolean')
      }
      expect(Object.keys(caps.cards).sort()).toEqual([...CARD_KEYS].sort())
    }
  })

  it('every engine + card has a human label', () => {
    for (const eng of ENGINE_KEYS) expect(ENGINE_LABELS[eng]).toBeTruthy()
    for (const card of CARD_KEYS) expect(CARD_LABELS[card]).toBeTruthy()
  })

  it('every unsupported card carries a why-reason (for the greyed tooltip)', () => {
    for (const eng of ENGINE_KEYS) {
      for (const card of CARD_KEYS) {
        const c = ENGINE_CAPABILITIES[eng].cards[card]
        if (!c.enabled) {
          expect(c.reason, `${eng}.${card} reason`).toBeTruthy()
          expect(c.domAnchorId, `${eng}.${card} anchor is null when unsupported`).toBeNull()
        } else {
          expect(c.domAnchorId, `${eng}.${card} anchor when enabled`).toBeTruthy()
        }
      }
    }
  })
})

describe('engine capability descriptor — PARITY vs audited census', () => {
  for (const eng of ENGINE_KEYS) {
    it(`${eng}: enabled set + anchors match the census exactly`, () => {
      for (const card of CARD_KEYS) {
        const cens = CENSUS[eng][card]
        const c = ENGINE_CAPABILITIES[eng].cards[card]
        const censusEnabled = 'on' in cens
        expect(c.enabled, `${eng}.${card} enabled parity`).toBe(censusEnabled)
        if (censusEnabled) {
          expect(c.domAnchorId, `${eng}.${card} anchor parity`).toBe(cens.on)
        }
      }
    })
  }
})

describe('engine capability descriptor — PARITY vs live index.html', () => {
  for (const eng of ENGINE_KEYS) {
    it(`${eng}: enabled anchors EXIST and unsupported probes are ABSENT in the DOM`, () => {
      for (const card of CARD_KEYS) {
        const cens = CENSUS[eng][card]
        if ('on' in cens) {
          expect(idPresent(cens.on), `enabled ${eng}.${card} anchor ${cens.on} in DOM`).toBe(true)
        } else {
          expect(idPresent(cens.off), `unsupported ${eng}.${card} probe ${cens.off} absent from DOM`).toBe(false)
        }
      }
    })
  }

  it('has no active global cards after shape comparison was archived', () => {
    expect(GLOBAL_CARDS).toEqual([])
  })
})

describe('engine capability descriptor — helper API', () => {
  it('enabledCardKeys returns exactly the census-enabled cards', () => {
    for (const eng of ENGINE_KEYS) {
      const expected = CARD_KEYS.filter(k => 'on' in CENSUS[eng][k])
      expect(enabledCardKeys(eng).sort()).toEqual(expected.sort())
    }
  })

  it('supportsCard agrees with the descriptor', () => {
    expect(supportsCard('oxdna', 'surface')).toBe(true)
    expect(supportsCard('cando', 'surface')).toBe(false)
    expect(supportsCard('mrdna', 'efield')).toBe(true)    // M6: field/anchors now reachable
    expect(supportsCard('mrdna', 'surface')).toBe(true)   // M8: ARBD repulsion plane now reachable
    expect(supportsCard('namd', 'surface')).toBe(true)
    expect(supportsCard('lammps', 'metrics')).toBe(false)   // no longer a selectable engine → false
    expect(supportsCard('bogus', 'efield')).toBe(false)
    expect(supportsCard('oxdna', 'bogus')).toBe(false)
  })

  it('cardReason is null for supported, a string for unsupported', () => {
    expect(cardReason('oxdna', 'efield')).toBeNull()
    expect(cardReason('mrdna', 'efield')).toBeNull()          // M6: now supported
    expect(cardReason('mrdna', 'surface')).toBeNull()         // M8: now supported
  })

  it('engineCards returns the full ordered stack with resolved fields', () => {
    const cards = engineCards('cando')
    expect(cards.map(c => c.key)).toEqual(CARD_KEYS)
    const surface = cards.find(c => c.key === 'surface')
    expect(surface.enabled).toBe(false)
    expect(surface.label).toBe(CARD_LABELS.surface)
    expect(surface.reason).toBeTruthy()
  })
})
