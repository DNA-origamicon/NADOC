"""Explicit empty-document VR authoring scene; never substitutes for failed geometry."""
from backend.core.extrude_plane import extrude_plane_record


def empty_authoring_scene(design, representation='full', coloring='strand'):
    # A document with authored objects must use normal geometry generation, even
    # when those objects currently produce no pixels (errors must remain visible).
    authored = ('helices', 'strands', 'overhangs', 'protein_assets', 'protein_attachments',
                'nanoparticles', 'extensions', 'crossovers', 'forced_ligations')
    if any(getattr(design, field, ()) for field in authored):
        return None
    if representation not in ('full', 'cylinders', 'ballstick', 'stick'):
        raise ValueError('invalid representation')
    if coloring not in ('strand', 'base', 'cluster', 'cpk'):
        raise ValueError('invalid coloring')
    return '\n'.join(['NADOCVR 14 '+representation+' '+coloring,
                      extrude_plane_record(design), 'Q empty_authoring',
                      *('R '+rep for rep in ('full', 'cylinders', 'ballstick', 'stick'))])+'\n'
