/** Pure canonical selection state + reducer. No store, DOM, renderer, or API imports. */

import {
  normalizeSelectionRef, selectionRefKey, selectionRefsEqual,
  dedupeSelectionRefs, reconcileSelectionRefs,
} from './selection_ref.js'
import { normalizeLevel } from './selection_level.js'

export const SELECTION_CONTEXTS = Object.freeze(['design', 'assembly'])
const CONTEXTS = new Set(SELECTION_CONTEXTS)

const contextOrDesign = context => CONTEXTS.has(context) ? context : 'design'
const last = items => items.length ? items[items.length - 1] : null

export function createSelectionState({ context = 'design', level = 'default', items = [], primary = null } = {}) {
  const refs = dedupeSelectionRefs(items)
  const normalizedPrimary = normalizeSelectionRef(primary)
  const primaryRef = normalizedPrimary
    ? refs.find(ref => selectionRefsEqual(ref, normalizedPrimary)) ?? last(refs)
    : last(refs)
  return {
    context: contextOrDesign(context),
    level: normalizeLevel(level),
    items: refs,
    primary: primaryRef ?? null,
  }
}

/** Opening/reloading any design or assembly always returns to default selection level. */
export function resetSelectionForReload(context = 'design') {
  return createSelectionState({ context: contextOrDesign(context), level: 'default' })
}

function withItems(state, items, primary = last(items)) {
  return createSelectionState({ ...state, items, primary })
}

function promoteToMostRecent(items, refs) {
  const promoted = new Set(refs.map(selectionRefKey))
  return [...items.filter(item => !promoted.has(selectionRefKey(item))), ...refs]
}

export function reduceSelection(current, intent = {}) {
  const state = createSelectionState(current)
  switch (intent.type) {
    case 'clear':
      return withItems(state, [], null)
    case 'setLevel':
      return { ...state, level: normalizeLevel(intent.level) }
    case 'reload':
    case 'changeContext':
      return resetSelectionForReload(intent.context ?? state.context)
    case 'replace': {
      const refs = dedupeSelectionRefs(intent.refs ?? (intent.ref ? [intent.ref] : []))
      return withItems(state, refs)
    }
    case 'select': {
      const ref = normalizeSelectionRef(intent.ref)
      if (!ref) return state
      // Approved fixed-level rule: a plain re-click of the sole item clears it.
      if (state.items.length === 1 && selectionRefsEqual(state.items[0], ref)) {
        return withItems(state, [], null)
      }
      return withItems(state, [ref], ref)
    }
    case 'toggle': {
      const ref = normalizeSelectionRef(intent.ref)
      if (!ref) return state
      const found = state.items.findIndex(item => selectionRefsEqual(item, ref))
      if (found < 0) return withItems(state, [...state.items, ref], ref)
      const items = state.items.filter((_, index) => index !== found)
      return withItems(state, items, last(items))
    }
    case 'extend': {
      const refs = dedupeSelectionRefs(intent.refs ?? (intent.ref ? [intent.ref] : []))
      if (!refs.length) return state
      const items = promoteToMostRecent(state.items, refs)
      return withItems(state, items, last(refs))
    }
    default:
      return state
  }
}

export function reconcileSelection(current, isLive) {
  const state = createSelectionState(current)
  const items = reconcileSelectionRefs(state.items, isLive)
  const primarySurvives = state.primary && items.some(item => selectionRefsEqual(item, state.primary))
  return withItems(state, items, primarySurvives ? state.primary : last(items))
}

export const selectedRefsOfKind = (state, kind) =>
  createSelectionState(state).items.filter(ref => ref.kind === kind)

export const selectedIdsOfKind = (state, kind) =>
  canonicalSelection(state).items.filter(ref => ref.kind === kind).map(ref => ref.id)

export const selectedOverhangIds = state => selectedIdsOfKind(state, 'overhang')
export const selectedExtensionIds = state => selectedIdsOfKind(state, 'extension')
export const selectedClusterIds = state => selectedIdsOfKind(state, 'cluster')
export const selectedCrossoverRefs = state =>
  canonicalSelection(state).items.filter(ref => ref.kind === 'crossover')
export const selectedEndRefs = state =>
  canonicalSelection(state).items.filter(ref => ref.kind === 'end')

export const primaryRefOfKind = (state, kind) => {
  const ref = canonicalSelection(state).primary
  return ref?.kind === kind ? ref : null
}

export const primaryOverhangId = state => primaryRefOfKind(state, 'overhang')?.id ?? null
export const primaryExtensionId = state => primaryRefOfKind(state, 'extension')?.id ?? null
export const primaryClusterId = state => primaryRefOfKind(state, 'cluster')?.id ?? null
export const primaryCrossoverRef = state => primaryRefOfKind(state, 'crossover')
export const primaryEndRef = state => primaryRefOfKind(state, 'end')

export const primarySelectionRef = state => createSelectionState(state).primary

/** Accept either the canonical slice itself or a full application-store snapshot. */
export const canonicalSelection = state =>
  createSelectionState(state?.selection && typeof state.selection === 'object' ? state.selection : (state ?? {}))

/** Direct strand ownership encoded by canonical strand/domain refs, in stable order. */
export function selectedStrandIds(state) {
  const ids = []
  const seen = new Set()
  for (const ref of canonicalSelection(state).items) {
    const id = ref.kind === 'strand' ? ref.id : ref.kind === 'domain' ? ref.strandId : null
    if (id && !seen.has(id)) { seen.add(id); ids.push(id) }
  }
  return ids
}

/** Direct strand owners plus parent strands related to overhang/extension refs. */
export function relatedStrandIds(state) {
  const ids = selectedStrandIds(state)
  const seen = new Set(ids)
  const design = state?.currentDesign
  for (const ref of canonicalSelection(state).items) {
    let id = null
    if (ref.kind === 'overhang') id = design?.overhangs?.find(item => item.id === ref.id)?.strand_id ?? null
    if (ref.kind === 'extension') id = design?.extensions?.find(item => item.id === ref.id)?.strand_id ?? null
    if (id && !seen.has(id)) { seen.add(id); ids.push(id) }
  }
  return ids
}

/** Rich, live relation for an overhang ref. Selection keeps only the stable id. */
export function overhangSelectionTarget(state, ref = primaryRefOfKind(state, 'overhang')) {
  if (!ref) return null
  const design = state?.currentDesign
  const overhang = design?.overhangs?.find(item => item.id === ref.id)
  if (!overhang) return null
  const strand = design?.strands?.find(item => item.id === overhang.strand_id) ?? null
  const domainIndex = strand?.domains?.findIndex(domain => domain.overhang_id === ref.id) ?? -1
  return {
    ref,
    overhang,
    strand,
    strandId: overhang.strand_id ?? null,
    domain: domainIndex >= 0 ? strand?.domains?.[domainIndex] ?? null : null,
    domainIndex: domainIndex >= 0 ? domainIndex : null,
  }
}

/** Rich, live relation for an extension ref. Selection keeps only the stable id. */
export function extensionSelectionTarget(state, ref = primaryRefOfKind(state, 'extension')) {
  if (!ref) return null
  const design = state?.currentDesign
  const extension = design?.extensions?.find(item => item.id === ref.id)
  if (!extension) return null
  return {
    ref,
    extension,
    strand: design?.strands?.find(item => item.id === extension.strand_id) ?? null,
    strandId: extension.strand_id ?? null,
  }
}
