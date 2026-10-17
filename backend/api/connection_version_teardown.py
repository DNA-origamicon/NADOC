"""Restore conflicting native connection owners before applying a version."""


def remove_conflicts(design, endpoint_ids):
    from backend.core.binding_relax import revert_bind_topology
    from backend.core.duplex import revert_duplex_relocation
    from backend.core.lattice import remove_linker_topology

    selected = frozenset(endpoint_ids)

    def involves(record):
        return bool(selected.intersection((record.overhang_a_id, record.overhang_b_id)))

    for connection in list(design.overhang_connections):
        if involves(connection):
            design = remove_linker_topology(design.model_copy(update={
                'overhang_connections': [c for c in design.overhang_connections
                                         if c.id != connection.id],
            }), connection.id)
    # Equal-length connections own restoration on the binding. Unequal-length
    # connections own it on the Duplex. Display-only duplexes have no snapshot.
    for binding in design.overhang_bindings:
        if involves(binding) and binding.bound and binding.prior_driven_topology:
            design = revert_bind_topology(design, binding.prior_driven_topology)
    removed_duplex_ids = set()
    for duplex in design.duplexes:
        if selected.intersection((duplex.left.overhang_id, duplex.right.overhang_id)):
            design = revert_duplex_relocation(design, duplex)
            removed_duplex_ids.add(duplex.id)
    return design.model_copy(update={
        'overhang_bindings': [b for b in design.overhang_bindings if not involves(b)],
        'duplexes': [d for d in design.duplexes if d.id not in removed_duplex_ids],
    })
