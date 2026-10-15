"""Apply selected loop/skip inputs without consulting simulation jobs or sessions."""

KINDS = frozenset({"autorefine-skips", "cando-autorefine-marks"})


def sequence_all(design, name):
    from backend.core.sequences import assign_scaffold_sequence, assign_staple_sequences
    from backend.core.models import StrandType

    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD and not strand.is_reference:
            design = assign_scaffold_sequence(design, name, strand_id=strand.id)[0]
    return assign_staple_sequences(design)


def select_scaffold(design, scaffold):
    from backend.core.sequences import SCAFFOLD_LIBRARY
    from backend.physics.oxdna_interface import count_undefined_bases

    if scaffold is not None:
        return scaffold
    for name, _length, _sequence in sorted(SCAFFOLD_LIBRARY, key=lambda t: t[1]):
        if count_undefined_bases(sequence_all(design, name))[0] == 0:
            return name
    longest = max(SCAFFOLD_LIBRARY, key=lambda t: t[1])
    raise ValueError(
        f"no library scaffold covers this design (longest is {longest[0]} at {longest[1]} nt) — it needs a custom/tiled scaffold"
    )


def resequence(design, scaffold=None):
    return sequence_all(design, select_scaffold(design, scaffold))


def build(kind, design, params):
    from backend.core.loop_skip_calculator import apply_loop_skips, clear_all_loop_skips
    from backend.core.models import LoopSkip

    design = clear_all_loop_skips(design)
    if kind == "cando-autorefine-marks":
        mods = {
            hid: [
                LoopSkip(bp_index=int(bp), delta=int(delta))
                for bp, delta in sorted(bps.items(), key=lambda item: int(item[0]))
            ]
            for hid, bps in params["marks"].items()
            if bps
        }
    elif "skips" in params:
        mods = {
            hid: [LoopSkip(bp_index=int(bp), delta=-1) for bp in bps]
            for hid, bps in params["skips"].items()
            if bps
        }
    else:
        from backend.api.skip_twist_tuning import sq_lattice_periodic_skips

        mods = (
            sq_lattice_periodic_skips(design, int(params["skip_period"]))
            if params.get("skip_period") is not None
            else {}
        )
    if set(mods) - {h.id for h in design.helices}:
        raise ValueError("Refinement names a missing helix")
    return resequence(
        apply_loop_skips(design, mods) if mods else design, params.get("scaffold")
    )
