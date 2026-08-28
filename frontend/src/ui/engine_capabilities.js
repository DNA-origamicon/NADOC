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
// SNUPI is the SAME in-process FEM as CanDo, run with the anisotropic SNUPI material law
// (validated ≥ CanDo vs MD at $0), so it sits next to CanDo on the fast→accurate axis.
//
// BLADE is ARCHIVED (2026-07-20): removed from the selectable tabs. The box-free atomistic
// relax + "Use as NAMD seed" flow shipped and works, but the origami we currently care about
// have too many unconventional features for the seeding to be useful, and the whole line was
// consuming disproportionate effort. The code is intentionally KEPT — its label + capability
// block below, the panel/display/backend modules, and the NAMD seed_blade_job_id plumbing all
// remain dormant. To revive: put 'blade' back in ENGINE_KEYS (between 'cando' and 'snupi') and
// restore the parity test + #blade-jobs-panel display. See memory/project_blade_frontend.md.
export const ENGINE_KEYS = ['cando', 'snupi', 'mrdna', 'oxdna', 'namd']

export const ENGINE_LABELS = {
  oxdna: 'oxDNA',
  mrdna: 'mrDNA',
  cando: 'CanDo',
  blade: 'BLADE',
  snupi: 'SNUPI',
  namd: 'NAMD',
}

// The card universe (union across all panels), in unified-stack display order.
export const CARD_KEYS = [
  'run', 'joblist', 'advanced', 'anchors', 'efield', 'surface', 'viz', 'metrics',
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

// Shape comparison was archived on 2026-08-27. Keep the stable selector contract;
// archived global cards simply leave it empty.
export const GLOBAL_CARDS = []

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
      surface: on('mrdna-surface-toggle'),   // M8: ARBD repulsion plane (backend M7)
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
  // ARCHIVED (2026-07-20) — 'blade' is no longer in ENGINE_KEYS, so nothing reads this block;
  // kept intact so reviving the tab is a one-line change (re-add 'blade' to ENGINE_KEYS).
  blade: {
    label: ENGINE_LABELS.blade,
    cards: {
      run: on('blade-jobs-run-btn'),
      // A relax is a free (unrestrained) implicit-solvent run: there is no body-force term and
      // no Dirichlet BC in the OpenMM system we build, so an E-field or an anchor would be
      // silently ignored rather than applied. Say so instead of offering a dead control.
      efield: off('BLADE relax applies no external body force — the OpenMM system has no E-field term.'),
      anchors: off('BLADE relax is unrestrained; no positional restraints are applied to the OpenMM system.'),
      surface: off('BLADE is box-free implicit solvent — there is no wall or surface boundary.'),
      advanced: on('blade-jobs-adv-toggle'),
      viz: on('blade-display-toggle'),
      metrics: on('blade-metrics-toggle'),
      joblist: on('blade-jobs-list-toggle'),
    },
    protocols: ['relax'],
    advancedParams: [
      'blade-jobs-correction', 'blade-jobs-minimize-iters', 'blade-jobs-langevin-ps',
      'blade-jobs-cutoff', 'blade-jobs-temp', 'blade-jobs-traj-frames', 'blade-jobs-platform',
    ],
  },
  snupi: {
    label: ENGINE_LABELS.snupi,
    cards: {
      run: on('snupi-jobs-coarse-btn'),
      efield: on('snupi-efield-toggle'),
      anchors: on('snupi-anchors-toggle'),
      surface: off('The SNUPI FEM has no hard-surface boundary condition (no wall BC in predict_shape).'),
      advanced: on('snupi-jobs-adv-toggle'),
      viz: on('snupi-display-toggle'),
      metrics: on('snupi-metrics-toggle'),
      joblist: on('snupi-jobs-list-toggle'),
    },
    protocols: ['coarse', 'fine'],
    // Same n_steps + with_rmsf knobs as CanDo, plus the SNUPI material-variant selector.
    advancedParams: ['snupi-jobs-n-steps', 'snupi-jobs-with-rmsf', 'snupi-jobs-material'],
  },
  namd: {
    label: ENGINE_LABELS.namd,
    cards: {
      run: on('md-jobs-run-btn'),
      efield: on('md-efield-toggle'),
      anchors: on('md-anchors-toggle'),
      surface: off('NAMD hard-surface / wall restraints are not wired yet.'),
      // NAMD has no Advanced drawer any more: every job parameter moved into the Job
      // Wizard (＋ New job), where it is shown per stage with the difference from the
      // previous stage and where its value came from.  The anchor is that button.
      advanced: on('md-jobs-new-btn'),
      viz: on('md-jobs-viz-toggle'),
      metrics: on('md-metrics-toggle'),
      joblist: on('md-jobs-list-toggle'),
    },
    protocols: ['run', 'production', 'ensemble', 'alpine-submit', 'resume'],
    // Wizard REQUEST fields, not DOM ids — the controls are built at runtime by
    // md_job_wizard.js rather than declared in index.html.
    advancedParams: [
      'padding_nm', 'box_mode', 'salt_mode', 'mg_conc_mM',
      'ion_conc_mM', 'minimize_steps', 'fast', 'early_stop_relax',
      'gpu_resident',
      'gpu_fallback_policy', 'threads', 'devices', 'force_soft',
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
