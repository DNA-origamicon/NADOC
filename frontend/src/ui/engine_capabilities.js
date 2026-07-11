/**
 * engine_capabilities.js — the single source of truth for what each simulation
 * engine can do (U1, "unified panel" track).
 *
 * Today the five simulation engines each have a bespoke sidebar panel
 * (`*_jobs_panel.js`) that renders its OWN stack of cards, and where an engine
 * doesn't support a card the panel simply omits it — so the E-field / Anchors /
 * Surface DOM is triplicated and "unsupported" reads as "missing". This module
 * is the data that will drive ONE shared card stack instead (U2 Forces factory,
 * U3 jobs-panel base, U4 engine selector): for every engine it lists EVERY card
 * in the universe marked either enabled (the panel renders it today) or
 * unsupported-with-a-reason (so U4 can grey-it-with-a-tooltip instead of hiding
 * it). It owns DATA only — no DOM, no I/O — so it stays trivially unit-testable
 * as the parity census in engine_capabilities.test.js.
 *
 * `domAnchorId` is the stable id of the card's toggle/button in index.html; it is
 * the seam the shared factories will mount onto and the anchor the parity oracle
 * verifies against the live DOM. It is null for unsupported cards.
 *
 * Card/enabled facts audited from the bespoke panels on 2026-07-08 — keep this in
 * sync with the panels until U2–U4 delete them; the test fails loudly otherwise.
 */

// Engine keys in sidebar-tab order — fast→accurate: CanDo (FEM) · mrDNA · oxDNA · NAMD
// (all-atom). "namd" is the backend/engine key; its DOM ids use the historical "md-"
// prefix. The Simulate default engine stays oxDNA (passed as `initial` in main.js), not
// ENGINE_KEYS[0]. LAMMPS is deliberately NOT a selectable engine: it's the auto-policy's
// CPU fallback (GPU busy → same oxDNA2 FF on multi-core), so its runs appear in the
// unified Simulate job list with an [L] badge instead of behind a tab (Phase C).
export const ENGINE_KEYS = ['cando', 'mrdna', 'oxdna', 'namd']

export const ENGINE_LABELS = {
  oxdna: 'oxDNA',
  mrdna: 'mrDNA',
  cando: 'CanDo',
  namd: 'NAMD',
}

// The card universe (union across all panels), in unified-stack display order.
// `comparison` is a GLOBAL card (one shared instance), not per-engine — see below.
export const CARD_KEYS = [
  'run', 'efield', 'anchors', 'surface', 'advanced', 'viz', 'metrics', 'joblist',
]

export const CARD_LABELS = {
  run: 'Run',
  efield: 'Electric field',
  anchors: 'Anchors',
  surface: 'Hard surface',
  advanced: 'Advanced parameters',
  viz: 'Visualizations',
  metrics: 'Metrics',
  joblist: 'Jobs',
}

// Shared cross-engine card(s) shown once regardless of the selected engine.
export const GLOBAL_CARDS = [
  { key: 'comparison', label: 'Shape comparison', domAnchorId: 'shape-compare-toggle' },
]

// Small helpers to keep the per-engine literal below terse.
const on = (id) => ({ enabled: true, domAnchorId: id, reason: null })
const off = (reason) => ({ enabled: false, domAnchorId: null, reason })

/**
 * Per-engine capability descriptor.
 *   cards[key]      -> { enabled, domAnchorId, reason }
 *   protocols       -> the run kinds the engine offers (labels)
 *   advancedParams  -> the advanced-drawer input ids (the param schema)
 */
export const ENGINE_CAPABILITIES = {
  oxdna: {
    label: ENGINE_LABELS.oxdna,
    cards: {
      run: on('oxdna-jobs-run-btn'),
      efield: on('efield-toggle'),
      anchors: on('oxdna-anchors-toggle'),
      surface: on('oxdna-floor-toggle'),
      advanced: on('oxdna-jobs-adv-toggle'),
      viz: on('oxdna-jobs-viz-toggle'),
      metrics: on('oxdna-metrics-toggle'),
      joblist: on('oxdna-jobs-list-toggle'),
    },
    protocols: ['relax', 'live', 'production', 'autorefine'],
    advancedParams: [
      'oxdna-jobs-backend', 'oxdna-jobs-device', 'oxdna-jobs-salt',
      'oxdna-jobs-mc-steps', 'oxdna-jobs-md-steps', 'oxdna-jobs-equil-steps',
      'oxdna-jobs-bp-gate',
    ],
  },
  mrdna: {
    label: ENGINE_LABELS.mrdna,
    cards: {
      run: on('mrdna-jobs-coarse-btn'),
      efield: on('mrdna-efield-toggle'),
      anchors: on('mrdna-anchors-toggle'),
      surface: off('mrDNA has no hard-surface boundary condition.'),
      advanced: on('mrdna-jobs-adv-toggle'),
      viz: on('mrdna-jobs-display-toggle'),
      metrics: off('mrDNA shows a curvature readout and feeds the comparison card; no metrics card yet.'),
      joblist: on('mrdna-jobs-list-toggle'),
    },
    protocols: ['coarse', 'fine'],
    advancedParams: [
      'mrdna-jobs-coarse-steps', 'mrdna-jobs-output-period', 'mrdna-jobs-device',
    ],
  },
  cando: {
    label: ENGINE_LABELS.cando,
    cards: {
      run: on('cando-jobs-coarse-btn'),
      efield: on('cando-efield-toggle'),
      anchors: on('cando-anchors-toggle'),
      surface: off('CanDo FEM has no hard-surface boundary condition.'),
      advanced: on('cando-jobs-adv-toggle'),
      viz: on('cando-display-toggle'),
      metrics: on('cando-metrics-toggle'),
      joblist: on('cando-jobs-list-toggle'),
    },
    protocols: ['coarse', 'fine', 'autorefine'],
    advancedParams: ['cando-jobs-n-steps', 'cando-jobs-with-rmsf'],
  },
  namd: {
    label: ENGINE_LABELS.namd,
    cards: {
      run: on('md-jobs-run-btn'),
      efield: on('md-efield-toggle'),
      anchors: on('md-anchors-toggle'),
      surface: off('NAMD hard-surface / wall restraints are not wired yet.'),
      advanced: on('md-jobs-adv-toggle'),
      viz: on('md-jobs-viz-toggle'),
      metrics: on('md-metrics-toggle'),
      joblist: on('md-jobs-list-toggle'),
    },
    protocols: ['run', 'production', 'ensemble', 'alpine-submit', 'resume'],
    advancedParams: [
      'md-jobs-preset', 'md-jobs-threads', 'md-jobs-devices', 'md-jobs-salt-mode',
      'md-jobs-mg', 'md-jobs-nacl', 'md-jobs-padding', 'md-jobs-watershell',
      'md-jobs-minsteps', 'md-jobs-autostart', 'md-jobs-fast', 'md-jobs-early-stop',
    ],
  },
}

/** Does `engineKey`'s panel support `cardKey` today? Safe on unknown keys. */
export function supportsCard(engineKey, cardKey) {
  const c = ENGINE_CAPABILITIES[engineKey]?.cards?.[cardKey]
  return !!(c && c.enabled)
}

/** The why-tooltip for an unsupported card, else null (supported/unknown). */
export function cardReason(engineKey, cardKey) {
  const c = ENGINE_CAPABILITIES[engineKey]?.cards?.[cardKey]
  return c && !c.enabled ? c.reason : null
}

/** The card keys an engine supports today, in CARD_KEYS order. */
export function enabledCardKeys(engineKey) {
  return CARD_KEYS.filter(k => supportsCard(engineKey, k))
}

/**
 * The full ordered card stack for an engine — every card in the universe with its
 * resolved {key,label,enabled,domAnchorId,reason}. This is what a unified panel
 * iterates to render supported cards live and unsupported cards greyed-with-tooltip.
 */
export function engineCards(engineKey) {
  const caps = ENGINE_CAPABILITIES[engineKey]
  if (!caps) return []
  return CARD_KEYS.map(key => ({
    key,
    label: CARD_LABELS[key],
    enabled: caps.cards[key].enabled,
    domAnchorId: caps.cards[key].domAnchorId,
    reason: caps.cards[key].reason,
  }))
}
