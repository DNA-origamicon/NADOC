/** Join sessions survive metadata/save acknowledgements, never native edits. */
const FIELDS = ['lattice_type', 'lattice_frames', 'helices', 'strands', 'deformations', 'cluster_transforms',
  'nucleotide_transforms', 'cluster_joints', 'cluster_join_constraints', 'overhangs', 'overhang_connections', 'overhang_bindings', 'duplexes',
  'flexible_segment_marks', 'flexible_connections', 'extensions', 'photoproduct_junctions', 'crossovers',
  'crossover_constraints', 'forced_ligations', 'protein_assets', 'protein_attachments', 'nanoparticles', 'nanoparticle_conjugations']

export const clusterJoinNativeSignature = design => JSON.stringify(FIELDS.map(key => design?.[key] ?? null))
