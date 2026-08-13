/**
 * Pure renderer-neutral highlight descriptor compiled from canonical selection.
 *
 * This is the boundary between logical selection and representation-specific
 * painting. It contains stable refs/IDs/keys only—never meshes, Three.js objects,
 * DOM nodes, or cached renderer entries. Individual renderers may resolve these
 * identities against their current live geometry.
 */

import { canonicalSelection } from './selection_model.js'

export function selectionHighlightDescriptor(state) {
  const selection = canonicalSelection(state)
  const byKind = kind => selection.items.filter(ref => ref.kind === kind)
  return {
    context: selection.context,
    primary: selection.primary,
    clusterIds: byKind('cluster').map(ref => ref.id),
    strandIds: byKind('strand').map(ref => ref.id),
    domains: byKind('domain').map(ref => ({ strandId: ref.strandId, domainIndex: ref.domainIndex })),
    baseKeys: byKind('base').map(ref => ref.key),
    endKeys: byKind('end').map(ref => ref.key),
    bonds: byKind('bond').map(ref => ({
      fromKey: ref.fromKey, toKey: ref.toKey, strandId: ref.strandId ?? null,
    })),
    crossovers: byKind('crossover').map(ref => ({ id: ref.id, subtype: ref.subtype })),
    overhangIds: byKind('overhang').map(ref => ref.id),
    extensionIds: byKind('extension').map(ref => ref.id),
    proteinIds: byKind('protein').map(ref => ref.id),
  }
}

export const highlightDescriptorIsEmpty = descriptor =>
  !descriptor || ![
    'clusterIds', 'strandIds', 'domains', 'baseKeys', 'endKeys', 'bonds',
    'crossovers', 'overhangIds', 'extensionIds', 'proteinIds',
  ].some(key => descriptor[key]?.length)
