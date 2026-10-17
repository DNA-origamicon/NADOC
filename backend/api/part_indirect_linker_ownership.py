"""Exact removal ownership for existing native zero-bridge linker topology."""
from backend.core.models import StrandType


def removed_resources(design, index, connection, targets, path):
    from backend.api.part_connection_application_commands import _fail
    from backend.core.lattice import _make_complement_domain, _zero_bridge_side_order

    prefix = f'__lnk__{connection.id}'
    identity = prefix + '__s'
    if (connection.linker_type != 'ss' or connection.length_unit != 'bp'
            or connection.overhang_a_id == connection.overhang_b_id
            or any(h.id.startswith(prefix) for h in design.helices)
            or {s.id for s in design.strands if s.id.startswith(prefix)} != {identity}):
        _fail('Indirect linker has incomplete or prefix-colliding ownership',
              'overhang_connection', connection.id, path)
    strand = index[('strand', identity)]
    by_side = {'a': connection.overhang_a_id, 'b': connection.overhang_b_id}
    expected = [_make_complement_domain(targets[by_side[side]][2], by_side[side])
                for side in _zero_bridge_side_order(connection)]
    if strand.strand_type != StrandType.LINKER or strand.is_reference or strand.domains != expected:
        _fail('Indirect linker has authored topology outside its native ownership', 'strand', identity, path)
    return {('overhang_connection', connection.id), ('strand', identity)}
