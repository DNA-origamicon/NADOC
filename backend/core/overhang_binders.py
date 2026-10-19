"""Overhang binder creation that refuses an already occupied complementary slot.

Kept outside the numerically hashed modules (``lattice``) so this guard does not
change native-engine implementation manifests. Every binder entry point (Generate
binder, nanoparticle/protein attachment and their recorded commands) uses it.
"""


class BinderSlotOccupied(ValueError):
    """The overhang's complementary slots already hold another strand."""


def make_binder_checked(design, overhang_id, *, strand_id=None):
    from backend.core.lattice import make_binder_for_overhang

    updated = make_binder_for_overhang(design, overhang_id, strand_id=strand_id)
    binder = updated.strands[-1]
    for comp in binder.domains:
        lo, hi = sorted((comp.start_bp, comp.end_bp))
        for strand in design.strands:
            if strand.is_reference:
                continue
            for dom in strand.domains:
                d_lo, d_hi = sorted((dom.start_bp, dom.end_bp))
                if (dom.helix_id == comp.helix_id and dom.direction == comp.direction
                        and d_lo <= hi and lo <= d_hi):
                    raise BinderSlotOccupied(
                        f"Overhang {overhang_id!r} is already paired by strand {strand.id!r}; "
                        "a slot can hold only one base.")
    return updated
