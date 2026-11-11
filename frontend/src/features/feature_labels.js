/** User-facing tool names. Recipe identifiers never serve as display labels. */
const names = new Map()
function family(name, kinds) { for (const kind of kinds.split(' ')) names.set(kind, name) }
family('Annotations', 'annotations-state')
family('View Volumes', 'view-volumes-state')
family('Extrude', 'bundle-create extrude-segment extrude-continuation extrude-deformed-continuation extrude-frame overhang-extrude')
family('Move/Rotate', 'cluster_op cluster-pose placement-poses nucleotide-transform nucleotide-transform-batch nucleotide-transform-delete assembly-transform-group assembly-transform-instance assembly-transform-instance-cluster')
family('Bend', 'bend')
family('Twist', 'twist')
family('Sweep', 'sweep')
family('Nick', 'nick nick-batch')
family('Crossover', 'crossover-place crossover-place-batch crossover-delete auto-crossover')
family('Group', 'group-create group-update group-organize group-dissolve cluster-dissolve assembly-create-group assembly-ungroup assembly-patch-group assembly-duplicate-group assembly-delete-group')
family('Make Cluster', 'cluster_create')
family('Join', 'cluster-join')
family('Orient', 'overhang_rotation')
family('Fine Routing', 'routing-cluster')
family('Circle', 'circle-segment')
family('Circular Pattern', 'circular-pattern')
family('Linear Pattern', 'linear-pattern')
family('Paste', 'cluster-paste element-paste')
family('Sequence', 'overhang-sequence strand-sequence assign-scaffold-sequence assign-staple-sequences')
family('Auto Scaffold', 'auto-scaffold auto-scaffold-seamed auto-scaffold-matched auto-scaffold-seamless auto-scaffold-bounded-section auto-scaffold-sections auto-scaffold-connectivity-section')
family('Auto Staple', 'full-autostaple')
family('Auto Break', 'auto-break')
family('Auto Merge', 'auto-merge')
family('Polymerize', 'route-for-polymerization assembly-polymerize assembly-polymerize-periodic assembly-polymerize-belt')
family('Overhang', 'overhang-bulk create-near-ends create-far-ends')
family('Extension', 'extension-upsert extension-delete')
family('Duplex', 'duplex-create duplex-connect duplex-patch duplex-delete duplex-sync-bindings duplex-relax assembly-duplex-add assembly-duplex-connect assembly-duplex-patch assembly-duplex-delete assembly-duplex-sync')
family('Linker', 'linker-add linker-patch linker-delete')
family('Flexible Segment', 'flexible-segment-mark flexible-segment-unmark flexible-relax')
family('Loop/Skip', 'apply-loop-skips autorefine-skips cando-autorefine-marks')
family('Joint', 'joint-place joint-update joint-delete assembly-add-joint assembly-delete-joint')
family('Mate', 'assembly-create-mate')
family('Connector', 'assembly-add-connector assembly-delete-connector')
family('Part', 'assembly-add-instance assembly-delete-instance assembly-duplicate-instance')
family('Gear', 'assembly-create-gear assembly-delete-gear')
family('Belt', 'assembly-create-belt assembly-delete-belt assembly-create-belt-rider assembly-delete-belt-rider')
family('Overhang Connection', 'assembly-overhang-bind assembly-overhang-bind-patch assembly-overhang-unbind assembly-overhang-connection-add assembly-overhang-connection-patch assembly-overhang-connection-delete assembly-overhang-connection-relax')
family('Import', 'aptamer-import cadnano-import scadnano-import dna-pdb-import protein-import')
family('Protein Attachment', 'protein-attach protein-attach-patch protein-attach-delete protein-conjugate')
family('Nanoparticle', 'nanoparticle-biotin-dna nanoparticle-create nanoparticle-patch nanoparticle-delete nanoparticle-conjugate nanoparticle-conjugation-delete nanoparticle-strand-bind nanoparticle-connection-version-create nanoparticle-connection-version-patch nanoparticle-connection-version-delete nanoparticle-connection-relax nanoparticle-attach-overhang')
family('Photoproduct', 'photoproduct-create photoproduct-relax photoproduct-delete')
family('Resize', 'strand-end-resize')
family('Shift', 'domain-shift')
family('Delete', 'strand-delete strand-delete-batch domain-delete helix-delete')
family('Generate Design', 'generate-design')
family('Curve', 'curve-path')
family('Branch', 'branch-seed fork-path')
family('Independent Section', 'independent-section-seed')
family('Connectivity Path', 'connectivity-path joined-crossbar-path')
family('Crossover Constraint', 'crossover-constraint-create crossover-constraint-delete')
family('Encode Curvature', 'encode-sweep-curvature')
family('Scaffold Budget', 'scaffold-budget-fit')

family('Ligate', 'ligate forced-ligation-create forced-ligation-delete forced-ligation-delete-batch forced-ligation-extra-bases')
family('Crossover', 'crossover-delete-batch crossover-extra-bases crossover-extra-bases-batch')
family('Helix', 'helix-add helix-add-at-cell helix-update helix-extend helix-reorder')
family('Strand', 'strand-add strand-update strand-patch strands-reference')
family('Domain', 'domain-add')
family('Color', 'strands-color-bulk')
family('Loop/Skip', 'loop-skip-insert loop-skip-clear loop-skip-clear-all loop-skip-twist loop-skip-bend')

export function featureOperationName(entry) {
  if (entry?.feature_type === 'cluster_op' && entry.source === 'folding-order') return 'Folding Order'
  if (entry?.op_kind === 'diagnostic-process') {
    const tools = { 'author-helix': 'Helix', 'author-strand': 'Strand', 'derive-connectivity': 'Crossover',
      'assembly-add': 'Add Part', 'assembly-polymerize': 'Polymerize Origami',
      'assembly-flatten': 'Prepare NAMD', 'phase-control': 'Molecular Placement Audit',
      'native-atoms': 'Molecular Placement Audit', 'terminal-candidate': 'Molecular Placement Audit',
      'mrdna-zero': 'Use as NAMD seed', 'document-name': 'Rename' }
    return tools[entry.params?.action] ?? 'Diagnostic Process'
  }
  if (entry?.feature_type === 'deformation') return names.get(entry.op_snapshot?.type) ?? 'Deform'
  return names.get(entry?.op_kind ?? entry?.op_subtype ?? entry?.feature_type) ?? 'Feature'
}

/** Compute ordinals from the current log, including suppressed entries. Persisted
 * labels remain elaboration: editing/reordering cannot leave stale F/tool numbers.
 */
export function featureLabels(log, prefix = 'F') {
  const counts = new Map()
  return log.map((entry, index) => {
    const name = featureOperationName(entry)
    const ordinal = (counts.get(name) ?? 0) + 1
    counts.set(name, ordinal)
    const raw = String(entry.label ?? entry.name ?? '').trim()
    const detail = [entry.op_kind, entry.op_subtype, entry.feature_type, name].includes(raw) ? '' : raw
    return `${prefix}${index + 1}: ${name} ${ordinal}${detail ? ` [${detail}]` : ''}`
  })
}
