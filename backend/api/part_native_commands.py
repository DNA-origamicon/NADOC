"""Native sequence, loop/skip and pattern adapters for independent recipe replay."""

from backend.core.models import LoopSkip

LOOP_COMMANDS = frozenset(
    {
        "loop-skip-insert",
        "loop-skip-twist",
        "loop-skip-bend",
        "loop-skip-clear",
        "loop-skip-clear-all",
    }
)
SEQUENCE_COMMANDS = frozenset({"assign-scaffold-sequence", "assign-staple-sequences"})
PATTERN_COMMANDS = frozenset({"circular-pattern", "linear-pattern"})


def build_loop(kind, design, params):
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        twist_loop_skips,
        bend_loop_skips,
    )

    if kind in {"loop-skip-clear", "loop-skip-clear-all"}:
        from backend.core.loop_skip_calculator import (
            clear_loop_skips,
            clear_all_loop_skips,
        )

        return (
            clear_all_loop_skips(design)
            if kind.endswith("-all")
            else clear_loop_skips(
                design, params["helix_ids"], params["plane_a_bp"], params["plane_b_bp"]
            )
        )
    if kind == "loop-skip-insert":
        helix = design.find_helix(params["helix_id"])
        if helix is None:
            raise ValueError("Loop/skip helix is missing")
        bp, delta = params["bp_index"], params["delta"]
        if delta not in {-1, 0, 1}:
            raise ValueError("Invalid loop/skip delta")
        if delta == 0:
            updated = helix.model_copy(
                update={"loop_skips": [m for m in helix.loop_skips if m.bp_index != bp]}
            )
            return design.copy_with(
                helices=[updated if h.id == helix.id else h for h in design.helices]
            )
        if not helix.bp_start <= bp < helix.bp_start + helix.length_bp:
            raise ValueError("Loop/skip position outside helix")
        mods = {helix.id: [LoopSkip(bp_index=bp, delta=delta)]}
    else:
        helices = [design.find_helix(hid) for hid in params["helix_ids"]]
        if not helices or any(h is None for h in helices):
            raise ValueError("Loop/skip target helix is missing")
        a, b = int(params["plane_a_bp"]), int(params["plane_b_bp"])
        if kind == "loop-skip-twist":
            mods = twist_loop_skips(helices, a, b, float(params["target_twist_deg"]))
        else:
            mods = bend_loop_skips(
                helices,
                a,
                b,
                float(params["radius_nm"]),
                float(params.get("direction_deg", 0)),
            )
    return apply_loop_skips(design, mods)


def build_sequence(kind, design, params):
    from backend.core.sequences import (
        assign_custom_scaffold_sequence,
        assign_scaffold_sequence,
        assign_staple_sequences,
    )

    if kind == "assign-staple-sequences":
        return assign_staple_sequences(design)
    sequence = params.get("custom_sequence")
    if sequence and sequence.strip():
        return assign_custom_scaffold_sequence(
            design, sequence, strand_id=params.get("strand_id")
        )[0]
    return assign_scaffold_sequence(
        design,
        params.get("scaffold_name", "M13mp18"),
        strand_id=params.get("strand_id"),
    )[0]
