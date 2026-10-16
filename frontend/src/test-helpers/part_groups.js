export function groupDesign() {
  return { id: 'part', helices: [{ id: 'h', bp_start: 10, length_bp: 30 }],
    strands: [{ id: 's', domains: [
      { helix_id: 'h', start_bp: 12, end_bp: 16, direction: 'FORWARD' },
      { helix_id: 'h', start_bp: 30, end_bp: 22, direction: 'REVERSE' },
    ] }], cluster_transforms: [{ id: 'same', name: 'Placement', helix_ids: ['h'], domain_ids: [] }],
    group_organization: { version: 1, groups: [
      { id: 'same', name: 'Named tail', helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 1 }], color: '#abcdef', opacity: 0.7 },
      { id: 'whole', name: 'Whole', helix_ids: ['h'], domain_ids: [], color: null, opacity: 1 },
      { id: 'empty', name: 'Empty', helix_ids: [], domain_ids: [], color: null, opacity: 1 },
    ] } }
}
