"""Render recorded terminal attachments without inferring molecular connectivity."""


def extension_root_anchors(design):
    strands = {s.id: s for s in design.strands}
    anchors = {}
    for extension in getattr(design, 'extensions', ()):
        strand = strands.get(extension.strand_id)
        if strand is None or not strand.domains:
            continue
        five = str(getattr(extension.end, 'value', extension.end)) == 'five_prime'
        domain = strand.domains[0 if five else -1]
        anchors[extension.id] = (strand.id, domain.helix_id,
            domain.start_bp if five else domain.end_bp,
            str(getattr(domain.direction, 'value', domain.direction)))
    return anchors


def is_extension_root_pair(first, second, anchors):
    """Only ext_k=0 and its recorded host endpoint form the root bond."""
    if bool(first.get('extension_id')) == bool(second.get('extension_id')):
        return False
    tail, host = (first, second) if first.get('extension_id') else (second, first)
    if tail.get('is_modification') or int(tail.get('bp_index', -1)) != 0:
        return False
    return (tail.get('strand_id') == host.get('strand_id') and
        anchors.get(tail['extension_id']) == (host.get('strand_id'),host.get('helix_id'),
            host.get('bp_index'),host.get('direction')))
