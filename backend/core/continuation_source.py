"""Canonical frame scope for continuation; independent of physical/view transforms."""

def continuation_source_helices(design, frame_id, plane):
    if frame_id is None:
        return design.helices
    frames = [f for f in design.lattice_frames if f.id == frame_id]
    if len(frames) != 1:
        raise ValueError('unknown continuation source frame')
    if frames[0].plane != plane:
        raise ValueError('continuation plane does not match source frame')
    return [h for h in design.helices if h.lattice_frame_id == frame_id]
